# qr_decode.py
import fitz  # PyMuPDF
import base64, zlib, sys, webbrowser
from pyzbar.pyzbar import decode
from PIL import Image
from io import BytesIO

def extract_qr_from_pdf(pdf_path):
    doc = fitz.open(pdf_path)
    qr_chunks = []

    for page_num in range(len(doc)):
        pix = doc[page_num].get_pixmap(dpi=300)
        img = Image.open(BytesIO(pix.tobytes("png")))
        codes = decode(img)
        if codes:
            data = codes[0].data.decode("utf-8")
            qr_chunks.append((page_num + 1, data))
        else:
            print(f"[WARN] Page {page_num + 1}: No QR code found")

    qr_chunks.sort()
    return [chunk for _, chunk in qr_chunks]

def decode_chunks_to_data(chunks):
    combined = ''.join(chunks)
    return zlib.decompress(base64.b64decode(combined)).decode("utf-8")

def main(pdf_path, output_html):
    print(f"[+] Reading QR codes from {pdf_path}...")
    chunks = extract_qr_from_pdf(pdf_path)
    if not chunks:
        print("[-] No QR codes found.")
        return
    print(f"[+] {len(chunks)} QR code(s) decoded. Reassembling content...")
    try:
        decoded_data = decode_chunks_to_data(chunks)
        with open(output_html, "w", encoding="utf-8") as f:
            f.write(decoded_data)
        print(f"[✓] HTML saved to {output_html}")
        webbrowser.open(f"file://{os.path.abspath(output_html)}")
    except Exception as e:
        print(f"[-] Error decoding QR chunks: {e}")

if __name__ == "__main__":
    if len(sys.argv) < 3:
        print("Usage: python qr_decode.py <input.pdf> <output.html>")
        sys.exit(1)
    import os
    main(sys.argv[1], sys.argv[2])

