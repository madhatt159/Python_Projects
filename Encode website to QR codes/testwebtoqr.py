#!/usr/bin/env python3
import argparse
import os
import sys
import zlib
import base64
import requests
from io import BytesIO
from PIL import Image
import qrcode
from concurrent.futures import ThreadPoolExecutor
from reportlab.pdfgen import canvas
from reportlab.lib.units import inch
from reportlab.lib.utils import ImageReader
from reportlab.pdfbase import pdfmetrics
from reportlab.pdfbase.cidfonts import UnicodeCIDFont

# register CJK font for Chinese
pdfmetrics.registerFont(UnicodeCIDFont('STSong-Light'))

# page & QR dimensions
LETTER_W_IN = 8.5
LETTER_H_IN = 11
FINAL_W_MM = 100
FINAL_W_IN = FINAL_W_MM / 25.4       # ≈3.937"
ROWS = 2                              # two QRs tall
DPI = 600
QR_PIXELS = int(DPI * FINAL_W_IN)
CHUNK_SIZE = 800                      # bytes per QR
JPEG_MAX = 300
JPEG_Q = 40

def downscale(content):
    try:
        img = Image.open(BytesIO(content))
        w = min(JPEG_MAX, img.width)
        h = int(img.height * (w / img.width))
        img = img.resize((w, h), Image.LANCZOS)
        buf = BytesIO()
        img.convert("RGB").save(buf, "JPEG", quality=JPEG_Q)
        return buf.getvalue(), "image/jpeg"
    except:
        return content, "image/png"

def inline_images(html, base_url):
    from bs4 import BeautifulSoup
    soup = BeautifulSoup(html, "html.parser")
    for tag in soup.find_all("img"):
        src = tag.get("src")
        if not src:
            continue
        try:
            url = requests.compat.urljoin(base_url, src)
            r = requests.get(url, timeout=5)
            data, mime = downscale(r.content)
            b64 = base64.b64encode(data).decode()
            tag["src"] = f"data:{mime};base64,{b64}"
        except:
            tag.decompose()
    return str(soup)

def chunk_data(data_str):
    return [data_str[i:i+CHUNK_SIZE] for i in range(0, len(data_str), CHUNK_SIZE)]

def make_qr(data_str):
    qr = qrcode.QRCode(error_correction=qrcode.constants.ERROR_CORRECT_H, border=4)
    qr.add_data(data_str)
    qr.make(fit=True)
    img = qr.make_image(fill_color="black", back_color="white").convert("RGB")
    return img.resize((QR_PIXELS, QR_PIXELS), Image.NEAREST)

def qr_to_buffer(data_str):
    img = make_qr(data_str)
    buf = BytesIO()
    img.save(buf, format="PNG", dpi=(DPI, DPI))
    buf.seek(0)
    return buf

def write_pdf(buffers, out_path, stats):
    W_pt = LETTER_W_IN * inch
    H_pt = LETTER_H_IN * inch
    crop_w = FINAL_W_IN * inch
    crop_h = ROWS * FINAL_W_IN * inch
    x0 = (W_pt - crop_w) / 2
    y0 = (H_pt - crop_h) / 2

    c = canvas.Canvas(out_path, pagesize=(W_pt, H_pt))

    # --- first page: stats + instructions ---
    y = H_pt - inch
    c.setFont("Helvetica-Bold", 14)
    c.drawString(inch/2, y, "DATA STATISTICS")
    y -= 18
    c.setFont("Helvetica", 12)
    c.drawString(inch/2, y, f"Original size   : {stats['raw_size']} bytes")
    y -= 14
    c.drawString(inch/2, y, f"Compressed size : {stats['compressed_size']} bytes")
    y -= 14
    c.drawString(inch/2, y, f"Base64 size     : {stats['b64_size']} bytes")
    y -= 14
    c.drawString(inch/2, y, f"Total QR codes  : {stats['num_chunks']}")
    y -= 24

    # English instructions
    en = [
        "DECODING INSTRUCTIONS (EN):",
        "1. Scan all QR codes in order.",
        "2. Concatenate the scanned outputs.",
        "3. Base64-decode the result.",
        "4. zlib-decompress the output.",
    ]
    c.setFont("Helvetica-Bold", 12)
    for line in en:
        c.drawString(inch/2, y, line)
        y -= 14
    y -= 10

    # Spanish instructions
    es = [
        "INSTRUCCIONES DE DECODIFICACIÓN (ES):",
        "1. Escanee todos los códigos QR en orden.",
        "2. Concatenar las salidas escaneadas.",
        "3. Decodificar Base64 el resultado.",
        "4. Descomprimir con zlib la salida.",
    ]
    c.setFont("Helvetica-Bold", 12)
    for line in es:
        c.drawString(inch/2, y, line)
        y -= 14
    y -= 10

    # Chinese instructions
    zh = [
        "解码说明 (ZH)：",
        "1. 按顺序扫描所有二维码。",
        "2. 将扫描输出连接成一个字符串。",
        "3. 对结果进行 Base64 解码。",
        "4. 使用 zlib 解压缩输出。",
    ]
    c.setFont("STSong-Light", 12)
    for line in zh:
        c.drawString(inch/2, y, line)
        y -= 14

    c.showPage()

    # --- subsequent pages: QR codes with crop marks ---
    pages = [buffers[i:i+ROWS] for i in range(0, len(buffers), ROWS)]
    for group in pages:
        mark = 10  # points
        corners = [(x0, y0), (x0+crop_w, y0), (x0, y0+crop_h), (x0+crop_w, y0+crop_h)]
        for cx, cy in corners:
            c.line(cx-mark, cy, cx+mark, cy)
            c.line(cx, cy-mark, cx, cy+mark)
        for idx, buf in enumerate(group):
            row = ROWS - 1 - idx
            x = x0
            y = y0 + row * FINAL_W_IN * inch
            c.drawImage(ImageReader(buf), x, y, width=crop_w, height=FINAL_W_IN*inch)
        c.showPage()

    c.save()

def main():
    p = argparse.ArgumentParser(description="Archival QR (100 mm×2) on letter w/ stats & instructions")
    p.add_argument("-d", action="store_true", help="print payload and exit")
    p.add_argument("-f", "--file", action="store_true", help="input is local file, not URL")
    p.add_argument("-t", "--threads", type=int, default=1, help="threads for QR generation")
    p.add_argument("input", help="URL or file path")
    p.add_argument("output", nargs="?", help="output PDF (omit with -d)")
    args = p.parse_args()

    if not args.d and not args.output:
        p.error("must supply output PDF unless -d")

    # load & compress
    if args.file:
        raw = open(args.input, "rb").read()
    else:
        raw_html = requests.get(args.input).text.encode()
        full = b"<!DOCTYPE html>\n" + inline_images(raw_html.decode(), args.input).encode()
        raw = full

    compressed = zlib.compress(raw)
    b64 = base64.b64encode(compressed).decode()

    stats = {
        "raw_size": len(raw),
        "compressed_size": len(compressed),
        "b64_size": len(b64),
        "num_chunks": len(chunk_data(b64))
    }

    if args.d:
        print(b64)
        return

    chunks = chunk_data(b64)
    total = len(chunks)
    print(f"[+] Generating {total} QR codes with {args.threads} threads")

    buffers = []
    with ThreadPoolExecutor(max_workers=args.threads) as ex:
        for i, buf in enumerate(ex.map(qr_to_buffer, chunks), start=1):
            print(f"[+] Generated QR {i}/{total}", flush=True)
            buffers.append(buf)

    print(f"[+] Writing PDF → {args.output}")
    write_pdf(buffers, args.output, stats)
    print(f"[✓] Saved: {args.output}")

if __name__ == "__main__":
    main()
