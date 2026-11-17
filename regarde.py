#!/usr/bin/env python3
"""
regarde: prepare any video so Claude can "watch" it.

    python3 regarde.py <lien ou fichier> [--root ~/regarde] [--force]

Writes ~/regarde/<nom-de-la-video>/ :
    video.mp4            the video (yt-dlp, or a copy of the local file)
    info.json            title, author, description, duration (links only)
    transcript.srt       subtitles from the platform, or a local whisper.cpp transcription
    transcript.txt       the same, one line per cue: [mm:ss.s] text
    frames/              one image every N s + one at every cut, timestamp burnt in
    frames.tsv           time, kind (regular|cut), file
    sheets/planche_NNN.jpg   5x4 contact sheets, 20 frames each, in time order
    resume.md            what was produced, duration, cuts, where everything is

Only free, local tools: yt-dlp, ffmpeg, whisper.cpp (model "base"). Never a paid API.
"""
import datetime as dt
import json
import os
import platform
import re
import shutil
import subprocess
import sys
import unicodedata
import urllib.request
import zipfile
from pathlib import Path

OS = platform.system()  # Darwin | Windows | Linux
HOME = Path.home()
DATA = Path(os.environ.get("LOCALAPPDATA", HOME / ".local" / "share")) / "regarde"
MODEL_URL = "https://huggingface.co/ggerganov/whisper.cpp/resolve/main/ggml-base.bin"


def say(msg):
    print(f"[regarde] {msg}", flush=True)


def run(cmd, check=True, capture=False, **kw):
    r = subprocess.run(cmd, text=True, capture_output=capture, **kw)
    if check and r.returncode != 0:
        err = (r.stderr or "")[-1500:] if capture else ""
        raise RuntimeError(f"command failed ({r.returncode}): {' '.join(map(str, cmd))}\n{err}")
    return r


def have(exe):
    return shutil.which(exe) is not None


# --------------------------------------------------------------- 1. tools
def install(pkg_brew, pkg_winget, pkg_apt):
    if OS == "Darwin":
        if not have("brew"):
            raise RuntimeError("Homebrew est requis : https://brew.sh")
        run(["brew", "install", pkg_brew])
    elif OS == "Windows":
        run(["winget", "install", "-e", "--id", pkg_winget, "--accept-source-agreements", "--accept-package-agreements"])
    else:
        sudo = [] if os.geteuid() == 0 else ["sudo"]
        r = run(sudo + ["apt-get", "install", "-y", pkg_apt], check=False)
        if r.returncode != 0:
            run(sudo + ["apt-get", "update", "-qq"])
            run(sudo + ["apt-get", "install", "-y", pkg_apt])


def ensure_tools():
    if not have("ffmpeg") or not have("ffprobe"):
        say("ffmpeg manquant : installation")
        install("ffmpeg", "Gyan.FFmpeg", "ffmpeg")
    if not have("yt-dlp"):
        say("yt-dlp manquant : installation")
        install("yt-dlp", "yt-dlp.yt-dlp", "yt-dlp")
    ver = run(["yt-dlp", "--version"], capture=True).stdout.strip()
    m = re.match(r"(\d{4})\.(\d{2})\.(\d{2})", ver)
    age = (dt.date.today() - dt.date(*map(int, m.groups()))).days if m else 999
    say(f"yt-dlp {ver} ({age} jours), {run(['ffmpeg', '-version'], capture=True).stdout.split(chr(10))[0]}")
    if age > 31:
        say("yt-dlp a plus d'un mois : mise à jour")
        if run(["yt-dlp", "-U"], check=False, capture=True).returncode != 0:
            if OS == "Darwin":
                run(["brew", "upgrade", "yt-dlp"], check=False)
            elif OS == "Windows":
                run(["winget", "upgrade", "-e", "--id", "yt-dlp.yt-dlp"], check=False)
            else:  # apt's yt-dlp lags behind the sites; pip keeps it current
                run([sys.executable, "-m", "pip", "install", "-q", "-U", "yt-dlp"], check=False)


def fetch(url, dest):
    dest.parent.mkdir(parents=True, exist_ok=True)
    if have("curl"):
        run(["curl", "-fsSL", "-o", str(dest), url])
    else:
        urllib.request.urlretrieve(url, dest)


def whisper_bin():
    """whisper.cpp's CLI, installed the first time (with the base model)."""
    for exe in ("whisper-cli", "whisper-cpp"):
        if have(exe):
            return shutil.which(exe)
    local = list(DATA.glob("whisper*/**/whisper-cli*"))
    local = [p for p in local if p.is_file() and os.access(p, os.X_OK)]
    if local:
        return str(local[0])
    say("whisper.cpp absent : installation (une seule fois)")
    if OS == "Darwin":
        run(["brew", "install", "whisper-cpp"])
        return shutil.which("whisper-cli")
    if OS == "Windows":
        rel = json.load(urllib.request.urlopen("https://api.github.com/repos/ggml-org/whisper.cpp/releases/latest"))
        asset = next(a for a in rel["assets"] if a["name"] == "whisper-bin-x64.zip")
        z = DATA / "whisper-bin-x64.zip"
        fetch(asset["browser_download_url"], z)
        zipfile.ZipFile(z).extractall(DATA / "whisper-bin")
        return str(next((DATA / "whisper-bin").rglob("whisper-cli.exe")))
    # Linux: build from source
    for tool, pkg in (("git", "git"), ("cmake", "cmake"), ("c++", "build-essential")):
        if not have(tool):
            install(pkg, pkg, pkg)
    src = DATA / "whisper.cpp"
    if not src.exists():
        run(["git", "clone", "--depth", "1", "https://github.com/ggml-org/whisper.cpp", str(src)])
    run(["cmake", "-B", "build", "-DCMAKE_BUILD_TYPE=Release"], cwd=src, capture=True)
    run(["cmake", "--build", "build", "-j", "--config", "Release"], cwd=src, capture=True)
    return str(src / "build" / "bin" / "whisper-cli")


def whisper_model():
    m = DATA / "models" / "ggml-base.bin"
    if not m.exists() or m.stat().st_size < 100_000_000:
        say("modèle whisper « base » : téléchargement (~140 Mo, une seule fois)")
        fetch(MODEL_URL, m)
    return str(m)


# --------------------------------------------------------------- 2. the video
def slug(s):
    s = unicodedata.normalize("NFKD", s).encode("ascii", "ignore").decode()
    s = re.sub(r"[^a-zA-Z0-9]+", "-", s).strip("-").lower()
    return (s[:60].rstrip("-") or "video")


def is_url(x):
    return re.match(r"https?://", x) is not None


def needs_cookies(url):
    return re.search(r"(instagram\.com|tiktok\.com)", url) is not None


def ytdlp(args, url):
    """yt-dlp, retried with Chrome's cookies when Instagram or TikTok refuses."""
    r = run(["yt-dlp", *args, url], check=False, capture=True)
    if r.returncode != 0 and needs_cookies(url):
        say("refusé : nouvel essai avec --cookies-from-browser chrome")
        r = run(["yt-dlp", "--cookies-from-browser", "chrome", *args, url], check=False, capture=True)
    return r


def get_video(src, root, force):
    if is_url(src):
        r = ytdlp(["-J", "--no-playlist"], src)
        if r.returncode != 0:
            raise RuntimeError("yt-dlp n'arrive pas à lire ce lien :\n" + r.stderr[-1500:])
        info = json.loads(r.stdout)
        name = slug(info.get("title") or info.get("id") or "video")
        if len(name) < 8 and info.get("id"):
            name = f"{name}-{slug(str(info['id']))}"
        out = root / name
        out.mkdir(parents=True, exist_ok=True)
        (out / "info.json").write_text(json.dumps({k: info.get(k) for k in (
            "title", "uploader", "channel", "upload_date", "duration", "view_count", "like_count",
            "description", "webpage_url", "width", "height", "fps", "tags")}, ensure_ascii=False, indent=1))
        if force or not (out / "video.mp4").exists():
            say(f"téléchargement → {out / 'video.mp4'}")
            r = ytdlp(["--no-playlist", "-f", "bv*[ext=mp4]+ba[ext=m4a]/b[ext=mp4]/bv*+ba/b",
                       "--merge-output-format", "mp4", "--remux-video", "mp4",
                       "-o", str(out / "video.%(ext)s"), "--force-overwrites"], src)
            if r.returncode != 0:
                raise RuntimeError("téléchargement impossible :\n" + r.stderr[-1500:])
        return out, info
    p = Path(src).expanduser()
    if not p.exists():
        raise RuntimeError(f"fichier introuvable : {p}")
    out = root / slug(p.stem)
    out.mkdir(parents=True, exist_ok=True)
    if force or not (out / "video.mp4").exists():
        if p.suffix.lower() == ".mp4":
            shutil.copy2(p, out / "video.mp4")
        else:
            run(["ffmpeg", "-v", "error", "-y", "-i", str(p), "-c:v", "libx264", "-c:a", "aac", str(out / "video.mp4")])
    return out, {"title": p.stem, "webpage_url": str(p)}


def probe(video):
    j = json.loads(run(["ffprobe", "-v", "error", "-show_entries",
                        "format=duration:stream=codec_type,width,height,r_frame_rate", "-of", "json", str(video)],
                       capture=True).stdout)
    v = next((s for s in j["streams"] if s["codec_type"] == "video"), {})
    a = any(s["codec_type"] == "audio" for s in j["streams"])
    return float(j["format"]["duration"]), v.get("width", 0), v.get("height", 0), v.get("r_frame_rate", "?"), a


# --------------------------------------------------------------- transcript
def srt_to_txt(srt):
    """[mm:ss.s] text, with the rolling duplicates of auto-captions removed."""
    blocks = re.split(r"\n\s*\n", srt.read_text(encoding="utf-8", errors="ignore").strip())
    lines, last = [], ""
    for b in blocks:
        parts = b.strip().splitlines()
        tline = next((x for x in parts if "-->" in x), None)
        if not tline:
            continue
        h, m, s = re.match(r"(\d+):(\d+):(\d+[,.]\d+)", tline).groups()
        t = int(h) * 3600 + int(m) * 60 + float(s.replace(",", "."))
        text = " ".join(x for x in parts[parts.index(tline) + 1:]).strip()
        text = re.sub(r"<[^>]+>", "", text).strip()
        if not text or text == last:
            continue
        if last and text.startswith(last):
            text = text[len(last):].strip()
        if text:
            lines.append(f"[{int(t // 60):02d}:{t % 60:04.1f}] {text}")
            last = " ".join(x for x in parts[parts.index(tline) + 1:]).strip()
    return "\n".join(lines) + "\n"


def get_transcript(src, out, has_audio):
    for f in out.glob("subs*"):
        f.unlink()
    if is_url(src):
        say("sous-titres de la plateforme")
        ytdlp(["--no-playlist", "--write-subs", "--write-auto-subs", "--skip-download",
               "--sub-langs", "fr.*,en.*,.*-orig", "--convert-subs", "srt",
               "-o", str(out / "subs.%(ext)s")], src)
        subs = sorted(out.glob("subs*.srt"), key=lambda p: ("-orig" not in p.name, "auto" in p.name, p.name))
        if subs:
            shutil.copy2(subs[0], out / "transcript.srt")
            (out / "transcript.txt").write_text(srt_to_txt(out / "transcript.srt"), encoding="utf-8")
            return f"sous-titres de la plateforme ({subs[0].name})"
    if not has_audio:
        (out / "transcript.txt").write_text("(pas de piste audio)\n", encoding="utf-8")
        return "aucune (pas d'audio)"
    vd = run(["ffmpeg", "-hide_banner", "-i", str(out / "video.mp4"), "-vn", "-af", "volumedetect", "-f", "null", "-"],
             check=False, capture=True).stderr
    peak = re.search(r"max_volume: (-?[0-9.]+) dB", vd)
    if peak and float(peak.group(1)) < -50:
        (out / "transcript.txt").write_text("(piste audio muette)\n", encoding="utf-8")
        return "aucune (piste audio muette)"
    say("pas de sous-titres : transcription locale avec whisper.cpp (modèle base)")
    wav = out / "audio16k.wav"
    run(["ffmpeg", "-v", "error", "-y", "-i", str(out / "video.mp4"), "-ac", "1", "-ar", "16000", str(wav)])
    run([whisper_bin(), "-m", whisper_model(), "-f", str(wav), "-l", "auto", "-osrt",
         "-of", str(out / "transcript"), "-t", str(max(2, (os.cpu_count() or 4) - 1))], capture=True)
    wav.unlink(missing_ok=True)
    txt = srt_to_txt(out / "transcript.srt")
    if not txt.strip():
        txt = "(aucune parole détectée : musique ou sons seulement)\n"
    (out / "transcript.txt").write_text(txt, encoding="utf-8")
    return "whisper.cpp local (modèle base)"


# --------------------------------------------------------------- frames and sheets
def font_opt():
    for f in ("/usr/share/fonts/truetype/dejavu/DejaVuSans-Bold.ttf", "/System/Library/Fonts/Supplemental/Arial Bold.ttf",
              "/Library/Fonts/Arial Bold.ttf", "/System/Library/Fonts/Helvetica.ttc", "C:/Windows/Fonts/arialbd.ttf"):
        if Path(f).exists():
            return "fontfile='" + f.replace(":", r"\:") + "':"
    return ""


def extract(out, every, w, h):
    fr = out / "frames"
    if fr.exists():
        shutil.rmtree(fr)
    fr.mkdir()
    side = "480:-2" if w >= h else "-2:480"
    font = font_opt()
    stamp = (f"drawtext={font}text='%{{pts\\:hms}}{{LBL}}':x=10:y=10:fontsize=26:fontcolor=white:"
             f"box=1:boxcolor=black@0.65:boxborderw=8")
    jobs = [("regular", f"fps=1/{every},scale={side},showinfo," + stamp.replace("{LBL}", "")),
            ("cut", f"select='gt(scene\\,0.3)',scale={side},showinfo," + stamp.replace("{LBL}", "  COUPE"))]
    rows = []
    for kind, vf in jobs:
        r = run(["ffmpeg", "-hide_banner", "-y", "-i", str(out / "video.mp4"), "-vf", vf, "-vsync", "vfr",
                 "-q:v", "3", str(fr / f"{kind}_%05d.jpg")], capture=True)
        times = [float(t) for t in re.findall(r"pts_time:([0-9.]+)", r.stderr)]
        files = sorted(fr.glob(f"{kind}_*.jpg"))
        rows += [(t, kind, f.name) for t, f in zip(times, files)]
    rows.sort()
    (out / "frames.tsv").write_text("time\tkind\tfile\n" + "".join(f"{t:.2f}\t{k}\t{n}\n" for t, k, n in rows))
    seq = fr / "_seq"
    seq.mkdir()
    for i, (_, _, n) in enumerate(rows, 1):
        shutil.copy2(fr / n, seq / f"{i:05d}.jpg")
    sh = out / "sheets"
    if sh.exists():
        shutil.rmtree(sh)
    sh.mkdir()
    run(["ffmpeg", "-v", "error", "-y", "-framerate", "1", "-i", str(seq / "%05d.jpg"),
         "-vf", "tile=5x4:padding=6:margin=6:color=0x202020", "-q:v", "3", str(sh / "planche_%03d.jpg")])
    shutil.rmtree(seq)
    return rows, sorted(sh.glob("planche_*.jpg"))


# --------------------------------------------------------------- main
def main():
    args = [a for a in sys.argv[1:] if not a.startswith("--")]
    if not args:
        sys.exit("usage: regarde.py <lien ou fichier> [--root DIR] [--force]")
    root = Path(sys.argv[sys.argv.index("--root") + 1]).expanduser() if "--root" in sys.argv else HOME / "regarde"
    if "--root" in sys.argv:
        args = [a for a in args if a != sys.argv[sys.argv.index("--root") + 1]]
    src, force = args[0], "--force" in sys.argv

    ensure_tools()
    out, info = get_video(src, root, force)
    dur, w, h, fps, has_audio = probe(out / "video.mp4")
    every = 1 if dur < 120 else 2 if dur <= 600 else 10
    say(f"{dur:.1f} s, {w}x{h}, {fps} i/s : une image toutes les {every} s + une à chaque coupe")
    tsrc = get_transcript(src, out, has_audio)
    rows, sheets = extract(out, every, w, h)
    cuts = [t for t, k, _ in rows if k == "cut"]
    resume = f"""# {info.get('title') or out.name}

- Source : {info.get('webpage_url') or src}
- Auteur : {info.get('uploader') or info.get('channel') or '?'}  |  publié : {info.get('upload_date') or '?'}
- Durée : {dur:.1f} s  |  {w}x{h}  |  {fps} i/s  |  audio : {'oui' if has_audio else 'non'}
- Transcription : {tsrc} → transcript.txt
- Images : {len(rows)} ({len(rows) - len(cuts)} régulières toutes les {every} s, {len(cuts)} aux coupes) → frames.tsv
- Coupes détectées (s) : {', '.join(f'{t:.1f}' for t in cuts) or 'aucune'}
- Planches 5x4 ({len(sheets)}) : {', '.join(p.name for p in sheets)}
"""
    (out / "resume.md").write_text(resume, encoding="utf-8")
    print(resume)
    print(f"DOSSIER={out}")


if __name__ == "__main__":
    try:
        main()
    except RuntimeError as e:
        sys.exit(f"[regarde] ERREUR : {e}")
