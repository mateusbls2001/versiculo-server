from flask import Flask, request, jsonify, send_file
from PIL import Image, ImageDraw, ImageFont
import subprocess, os, uuid, random

app = Flask(__name__)
OUTPUT_DIR     = "/tmp/versiculo_imgs"
VIDEO_DURATION = 8
os.makedirs(OUTPUT_DIR, exist_ok=True)

# ── FONTS ──────────────────────────────────────────────────────────────────────
DM_SANS_BOLD = "/app/fonts/DMSans-Bold.ttf"
DM_SANS_REG  = "/app/fonts/DMSans-Regular.ttf"
FB_BOLD      = "/usr/share/fonts/truetype/dejavu/DejaVuSans-Bold.ttf"
FB_REG       = "/usr/share/fonts/truetype/dejavu/DejaVuSans.ttf"

def load_font(path, size):
    try:    return ImageFont.truetype(path, size)
    except: return ImageFont.load_default()

def sans_bold(size):
    for p in [DM_SANS_BOLD, FB_BOLD]:
        try: return ImageFont.truetype(p, size)
        except: pass
    return ImageFont.load_default()

def sans_reg(size):
    for p in [DM_SANS_REG, FB_REG]:
        try: return ImageFont.truetype(p, size)
        except: pass
    return ImageFont.load_default()

# ── CONFIG ─────────────────────────────────────────────────────────────────────
HANDLE = "@versiculo_diario001"

# ── HELPERS ────────────────────────────────────────────────────────────────────
def wrap_text(draw, text, font, max_width):
    words = text.split()
    lines, current = [], ""
    for word in words:
        test = (current + " " + word).strip()
        bb   = draw.textbbox((0,0), test, font=font)
        if bb[2]-bb[0] > max_width and current:
            lines.append(current)
            current = word
        else:
            current = test
    if current:
        lines.append(current)
    return lines

# ── FRAME CREATOR ──────────────────────────────────────────────────────────────
def create_frame(phrase, reference, palette_idx=None):
    W = H = 1080
    img  = Image.new('RGB', (W, H), (255, 255, 255))
    draw = ImageDraw.Draw(img)

    font_verse  = sans_bold(30)
    font_ref    = sans_reg(24)
    font_handle = sans_reg(20)

    lines   = wrap_text(draw, phrase, font_verse, W - 200)
    lh      = 30 + 14
    total_h = len(lines) * lh

    # Verso centralizado verticalmente
    y = (H - total_h) // 2 - 40
    for line in lines:
        bb = draw.textbbox((0,0), line, font=font_verse)
        tw = bb[2]-bb[0]
        draw.text(((W-tw)//2, y), line, font=font_verse, fill=(30, 30, 30))
        y += lh

    # Referência
    if reference:
        bb_r = draw.textbbox((0,0), reference, font=font_ref)
        tw_r = bb_r[2]-bb_r[0]
        draw.text(((W-tw_r)//2, y + 30), reference,
                  font=font_ref, fill=(100, 100, 100))

    # Handle
    bb_h = draw.textbbox((0,0), HANDLE, font=font_handle)
    tw_h = bb_h[2]-bb_h[0]
    draw.text(((W-tw_h)//2, H-55), HANDLE,
              font=font_handle, fill=(180, 180, 180))

    return img

def image_to_video(img, output_path, duration=VIDEO_DURATION):
    fp = f"/tmp/{uuid.uuid4()}.png"
    img.save(fp, 'PNG')
    cmd = ["ffmpeg","-y","-loop","1","-i",fp,
           "-vf",f"fade=in:0:15,fade=out:st={duration-1}:d=1,scale=1080:1080",
           "-c:v","libx264","-t",str(duration),
           "-pix_fmt","yuv420p","-movflags","+faststart",output_path]
    r = subprocess.run(cmd, capture_output=True, text=True)
    os.remove(fp)
    if r.returncode != 0:
        raise Exception(f"FFmpeg error: {r.stderr}")
    return output_path

def get_base_url(req):
    return req.host_url.rstrip('/').replace('http://','https://')

def parse_body(data):
    if not data or 'phrase' not in data:
        return None, None, None, ("Campo 'phrase' obrigatorio", 400)
    phrase    = data.get('phrase','').strip()
    reference = data.get('reference','').strip()
    palette   = data.get('palette_idx', None)
    if palette is not None:
        try: palette = int(palette)
        except: palette = None
    if not phrase:
        return None, None, None, ("Frase nao pode ser vazia", 400)
    return phrase, reference, palette, None

# ── ROUTES ─────────────────────────────────────────────────────────────────────
@app.route('/health', methods=['GET'])
def health():
    return jsonify({"status": "ok", "service": "versiculo-diario"})

@app.route('/generate-image-url', methods=['POST'])
def generate_image_url():
    phrase, reference, palette, err = parse_body(request.get_json())
    if err: return jsonify({"error": err[0]}), err[1]
    try:
        frame    = create_frame(phrase, reference, palette)
        img_id   = str(uuid.uuid4())
        out_path = os.path.join(OUTPUT_DIR, f"{img_id}.png")
        frame.save(out_path, 'PNG')
        base = get_base_url(request)
        return jsonify({"success": True,
                       "image_url": f"{base}/image/{img_id}",
                       "image_id": img_id,
                       "phrase": phrase})
    except Exception as e:
        return jsonify({"error": str(e)}), 500

@app.route('/generate-url', methods=['POST'])
def generate_video_url():
    data = request.get_json()
    phrase, reference, palette, err = parse_body(data)
    if err: return jsonify({"error": err[0]}), err[1]
    duration = int(data.get('duration', VIDEO_DURATION))
    try:
        frame    = create_frame(phrase, reference, palette)
        vid_id   = str(uuid.uuid4())
        out_path = os.path.join(OUTPUT_DIR, f"{vid_id}.mp4")
        image_to_video(frame, out_path, duration)
        base = get_base_url(request)
        return jsonify({"success": True,
                       "video_url": f"{base}/video/{vid_id}",
                       "video_id": vid_id,
                       "phrase": phrase})
    except Exception as e:
        return jsonify({"error": str(e)}), 500

@app.route('/image/<image_id>', methods=['GET'])
def get_image(image_id):
    try: uuid.UUID(image_id)
    except: return jsonify({"error": "Invalid ID"}), 400
    path = os.path.join(OUTPUT_DIR, f"{image_id}.png")
    if not os.path.exists(path): return jsonify({"error": "Not found"}), 404
    return send_file(path, mimetype='image/png')

@app.route('/video/<video_id>', methods=['GET'])
def get_video(video_id):
    try: uuid.UUID(video_id)
    except: return jsonify({"error": "Invalid ID"}), 400
    path = os.path.join(OUTPUT_DIR, f"{video_id}.mp4")
    if not os.path.exists(path): return jsonify({"error": "Not found"}), 404
    return send_file(path, mimetype='video/mp4')

if __name__ == '__main__':
    port = int(os.environ.get('PORT', 5000))
    app.run(host='0.0.0.0', port=port, debug=False)
