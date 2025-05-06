# qr_encode.py
import requests, base64, zlib, os, sys, tempfile
from bs4 import BeautifulSoup
from urllib.parse import urljoin
from PIL import Image
from io import BytesIO
import qrcode
from reportlab.pdfgen import canvas
from reportlab.lib.pagesizes import inch
from reportlab.lib.utils import ImageReader

PAGE_SIZE_INCH = 8
DPI = 600
PX = DPI * PAGE_SIZE_INCH
QR_PADDING_PX = int(0.6 * DPI)
QR_BOTTOM_OFFSET_PX = int(0.9 * DPI)
QR_DRAW_SIZE_PX = PX - 2 * QR_PADDING_PX - QR_BOTTOM_OFFSET_PX
CHUNK_SIZE = 1000
MAX_IMAGE_WIDTH = 300
JPEG_QUALITY = 40


def downscale_image(content):
    try:
        img = Image.open(BytesIO(content))
        w_percent = min(1.0, MAX_IMAGE_WIDTH / float(img.width))
        new_size = (int(img.width * w_percent), int(img.height * w_percent))
        img = img.resize(new_size, Image.LANCZOS)
        buf = BytesIO()
        img.convert("RGB").save(buf, format="JPEG", quality=JPEG_QUALITY)
        return buf.getvalue(), "image/jpeg"
    except Exception:
        return content, "image/png"


def inline_images(html, base_url):
    soup = BeautifulSoup(html, "html.parser")

    for tag in soup.find_all("img"):
        src = tag.get("src")
        if not src:
            continue
        try:
            img_url = urljoin(base_url, src)
            res = requests.get(img_url, timeout=5)
            content, mime = downscale_image(res.content)
            b64 = base64.b64encode(content).decode("utf-8")
            tag["src"] = f"data:{mime};base64,{b64}"
        except Exception:
            tag.decompose()

    return str(soup)


def compress_html(full_html):
    compressed = zlib.compress(full_html.encode("utf-8"))
    return base64.b64encode(compressed).decode("utf-8")


def chunk_data(data):
    return [data[i:i + CHUNK_SIZE] for i in range(0, len(data), CHUNK_SIZE)]


def create_qr_image(data, size_px):
    qr = qrcode.QRCode(
        error_correction=qrcode.constants.ERROR_CORRECT_H,
        border=4
    )
    qr.add_data(data)
    qr.make(fit=True)
    img = qr.make_image(fill_color="black", back_color="white").convert("RGB")
    return img.resize((size_px, size_px), Image.NEAREST)


def write_pdf(qr_chunks, output_pdf):
    c = canvas.Canvas(output_pdf, pagesize=(PAGE_SIZE_INCH * inch, PAGE_SIZE_INCH * inch))
    total = len(qr_chunks)

    for i, chunk in enumerate(qr_chunks, start=1):
        print(f"[+] Encoding page {i} of {total}")
        img = create_qr_image(chunk, QR_DRAW_SIZE_PX)
        tmp_img = tempfile.NamedTemporaryFile(delete=False, suffix=".png")
        img.save(tmp_img.name, dpi=(DPI, DPI))
        reader = ImageReader(tmp_img.name)

        x = QR_PADDING_PX * 72 / DPI
        y = (QR_PADDING_PX + QR_BOTTOM_OFFSET_PX) * 72 / DPI
        size = QR_DRAW_SIZE_PX * 72 / DPI

        c.drawImage(reader, x, y, width=size, height=size)
        c.setFont("Helvetica", 10)
        page_text = f"Page {i}"
        text_width = c.stringWidth(page_text, "Helvetica", 10)
        c.drawString(PAGE_SIZE_INCH * inch - x - text_width, QR_PADDING_PX * 72 / DPI / 2, page_text)

        os.remove(tmp_img.name)
        c.showPage()
    c.save()


def main(url, output_pdf):
    print(f"[+] Fetching: {url}")
    html = requests.get(url).text
    print("[+] Inlining images...")
    full_html = inline_images(html, url)
    full_html = "<!DOCTYPE html>\n" + full_html
    print("[+] Compressing and encoding...")
    b64 = compress_html(full_html)
    chunks = chunk_data(b64)
    print(f"[+] Writing {len(chunks)} QR codes to PDF...")
    write_pdf(chunks, output_pdf)
    print(f"[✓] PDF saved: {output_pdf}")


if __name__ == "__main__":
    if len(sys.argv) < 3:
        print("Usage: python qr_encode.py <url> <output.pdf>")
        sys.exit(1)
    main(sys.argv[1], sys.argv[2])
