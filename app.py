from flask import Flask, request, jsonify, send_file
from PIL import Image, ImageDraw, ImageFont
import subprocess, os, uuid, random

app = Flask(__name__)
OUTPUT_DIR     = "/tmp/versiculo_imgs"
VIDEO_DURATION = 8
os.makedirs(OUTPUT_DIR, exist_ok=True)

# ── FONTS ──────────────────────────────────────────────────────────────────────
LORA_BOLD = "/app/fonts/Lora-Bold.ttf"
LORA_REG  = "/app/fonts/Lora-Regular.ttf"
FB_BOLD   = "/usr/share/fonts/truetype/dejavu/DejaVuSans-Bold.ttf"
FB_REG    = "/usr/share/fonts/truetype/dejavu/DejaVuSans.ttf"

def load_font(path, size):
    try:    return ImageFont.truetype(path, size)
    except: return ImageFont.load_default()

def serif_bold(size):
    for p in [LORA_BOLD, FB_BOLD]:
        try: return ImageFont.truetype(p, size)
        except: pass
    return ImageFont.load_default()

def serif_reg(size):
    for p in [LORA_REG, FB_REG]:
        try: return ImageFont.truetype(p, size)
        except: pass
    return ImageFont.load_default()

# ── CONFIG ─────────────────────────────────────────────────────────────────────
HANDLE   = "@versiculo_diario001"
PALETTES = [
    (173, 216, 230),  # light blue
    (176, 224, 160),  # soft green
    (255, 218, 185),  # peach
    (216, 191, 216),  # lavender
    (255, 228, 181),  # warm yellow
    (175, 238, 238),  # turquoise
]

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

def draw_brush(draw, cx, cy, w, h, color, seed=42):
    rng = random.Random(seed)
    r, g, b = color
    for _ in range(18):
        ox = rng.randint(-int(w*0.25), int(w*0.25))
        oy = rng.randint(-int(h*0.30), int(h*0.30))
        ew = w + rng.randint(-int(w*0.10), int(w*0.10))
        eh = h + rng.randint(-int(h*0.15), int(h*0.15))
        a  = rng.randint(45, 95)
        draw.ellipse([cx-ew//2+ox, cy-eh//2+oy,
                      cx+ew//2+ox, cy+eh//2+oy], fill=(r,g,b,a))
    draw.ellipse([cx-w//2, cy-h//2, cx+w//2, cy+h//2], fill=(r,g,b,130))

# ── FRAME CREATOR ──────────────────────────────────────────────────────────────
def create_frame(phrase, reference, palette_idx=None):
    W = H = 1080
    img  = Image.new('RGBA', (W, H), (252, 252, 252, 255))
    draw = ImageDraw.Draw(img, 'RGBA')

    font_verse  = serif_bold(68)
    font_ref    = serif_reg(52)
    font_handle = load_font(FB_REG, 26)

    lines   = wrap_text(draw, phrase, font_verse, W - 160)
    lh      = 68 + 18
    total_h = len(lines) * lh

    pad      = 55
    brush_cx = W // 2
    brush_cy = H // 2 - 20
    brush_w  = W - 60
    brush_h  = total_h + pad * 2 + 60

    idx   = palette_idx if palette_idx is not None else random.randint(0, len(PALETTES)-1)
    color = PALETTES[idx % len(PALETTES)]
    draw_brush(draw, brush_cx, brush_cy, brush_w, brush_h, color, seed=idx*13+7)

    # Verse
    y = brush_cy - total_h // 2 + 10
    for line in lines:
        bb = draw.textbbox((0,0), line, font=font_verse)
        tw = bb[2]-bb[0]
        draw.text(((W-tw)//2, y), line, font=font_verse, fill=(30,30,30,255))
        y += lh

    # Reference
    if reference:
        ref_y = brush_cy + brush_h//2 + 28
        bb_r  = draw.textbbox((0,0), reference, font=font_ref)
        tw_r  = bb_r[2]-bb_r[0]
        draw.text(((W-tw_r)//2, ref_y), reference,
                 font=font_ref, fill=(50,50,50,220))

    # Handle
    bb_h = draw.textbbox((0,0), HANDLE, font=font_handle)
    tw_h = bb_h[2]-bb_h[0]
    draw.text(((W-tw_h)//2, H-55), HANDLE,
             font=font_handle, fill=(160,160,160,200))

    return img.convert('RGB')

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
