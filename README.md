# bada

An open-source tool that allows Large Language Models (LLMs) to run code directly on your local machine.

## Installation

### From .deb (Recommended)
Download the latest release from the [Releases](https://github.com/bada-tv-inc/bada/releases) page.

```bash
sudo dpkg -i bada_0.1.0_amd64.deb
```

### From Source
```bash
git clone https://github.com/bada-tv-inc/bada.git
cd bada
pip install -e .
```

## Usage

```bash
# Start with default model (gpt-4o)
bada start

# Use a different model
bada start --model claude-3-opus

# Auto-run mode (WARNING: Dangerous)
bada start --auto-run
```


## YouTube automation (`bada youtube`)

Drop in a raw recording; bada cuts it, captions it, writes the title/description/chapters,
and uploads it to YouTube as **private**. Nothing goes public until you review it and run `publish`.

```
raw.mp4 → whisper transcript → cut silences + retakes (LLM) → ffmpeg render
        → captions.srt → title / description / tags / chapters (LLM) → PRIVATE upload
                                                       you review in Studio → bada youtube publish
```

### Setup (one-time)
1. `pip install -e '.[youtube]'` and install `ffmpeg` (`sudo apt install ffmpeg` / `brew install ffmpeg`).
2. In [Google Cloud Console](https://console.cloud.google.com/): create a project, enable **YouTube Data API v3**,
   configure the OAuth consent screen (add yourself as a test user), and create an **OAuth client ID → Desktop app**.
   Download the JSON.
3. `bada youtube auth --client-secret ~/Downloads/client_secret_xxx.json`

### Use
```bash
bada youtube process raw.mp4            # one video → private upload
bada youtube process raw.mp4 --no-upload  # only produce files in raw_bada/
bada youtube watch ~/Videos/inbox       # every new video in the folder → private upload
bada youtube status ~/Videos/inbox      # what's been uploaded and still private
bada youtube publish <video_id>         # after you've checked it: make it public
bada youtube publish <video_id> --at 2026-10-10T19:00:00+09:00   # or schedule it
```

Each video gets a `<name>_bada/` folder with `transcript.json`, `edits.json` (every cut and why),
`captions.srt`, `package.json` and `final.mp4`, so you can check or redo any step.
Useful flags: `--no-silence`, `--no-retakes`, `--burn-subtitles`, `--whisper-model medium`, `--language en`, `--thumbnail thumb.jpg`.

### Limits to know
- **Audit required before anything can go public.** Videos uploaded from an API project that hasn't passed
  Google's [API compliance audit](https://support.google.com/youtube/contact/yt_api_form) are *locked* private,
  and neither `publish` nor Studio can unlock them. Upload + review works right away; apply for the audit
  (free, takes a few weeks) before you rely on `publish`.
- Default quota is 10,000 units/day and an upload costs ~1,600 → about 6 uploads per day.
- Custom thumbnails need a phone-verified channel.

## Reels research & production (`bada reels`)

Learn from 1M+ view reels in your niche, then cut **your** video the same way.

```
viral reel URLs ─► analyze ─► report ─► make (our video) ─► reel.mp4 + caption.txt
```

```bash
pip install -e '.[reels]'

# 1. Analyse viral reels (URLs you pick, one per line in urls.txt)
bada reels analyze --urls urls.txt --min-views 1000000
# 2. What repeats across them: formulas, hook rules, pacing, editing techniques
bada reels report
# 3. Make our reel following those formulas
bada reels make our_video.mp4
bada reels make our_video.mp4 --plan-only        # review/edit plan.json first
bada reels make our_video.mp4 --plan our_video_reel/plan.json
```

**analyze** writes `reels_research/<id>/` per reel:

| step | output |
|---|---|
| download, original quality (yt-dlp, best video+audio, no re-encode) | `video.mp4`, `info.json` (views, likes, caption, music) |
| speech to text, sentence level | `transcript.json` |
| first 3 s, one full-res frame every 0.125 s (24 frames) + contact sheet | `hook_frames/00.000s.png …`, `sheet.jpg` |
| hard cuts and audio spikes/clipping, per second | `signals.json` → `timeline` |
| element-by-element breakdown (vision LLM): hook, structure, format, editing, pacing, audio, CTA, formula, template | `analysis.json`, `analysis.md` |

**make** picks and reorders clips from our transcript to fit the best formula (strongest result first),
then renders 1080×1920 with full-screen / black-canvas layouts, punch-in “pop” zooms, one-word kinetic
captions, headlines, a whoosh on every cut and a comment-keyword CTA. Output: `<video>_reel/reel.mp4`,
`caption.txt`, `plan.json`. Nothing is posted; you review and post it yourself.

Notes: downloading other creators' reels is against Instagram's terms and they stay their copyright —
use them for private analysis only, never re-upload. If yt-dlp needs a login, pass
`--cookies-browser chrome` with a **separate** account, not the one you manage.

## License & Disclaimer
This project is licensed under the MIT License - see the [LICENSE](LICENSE) file for details.

**⚠️ DISCLAIMER**:  
**bada** executes code generated by an AI directly on your system. While it includes safety mechanisms (like user confirmation), **you are solely responsible for any systems modifications, file deletions, or damage caused by this tool.**
The authors (`bada-tv-inc`) accept no liability for any usage of this software. Use at your own risk.
