"""Generate SIH26034's fixed-size QR calibration reference.

The black QR symbol (excluding the quiet zone) is exactly 50 mm x 50 mm in the
vector PDF/SVG. Print at 100% / actual size; never use printer scaling.
"""
from pathlib import Path
import qrcode
from PIL import Image
from reportlab.pdfgen import canvas
from reportlab.lib.units import mm

ROOT=Path(__file__).resolve().parents[1]
OUT=ROOT/'calibration_reference'; OUT.mkdir(exist_ok=True)
PAYLOAD='SIH26034-QR-50MM'; QR_MM=50.0; MODULES=25; QUIET=4; DPI=600
module_mm=QR_MM/MODULES
total_mm=(MODULES+2*QUIET)*module_mm

qr=qrcode.QRCode(version=2,error_correction=qrcode.constants.ERROR_CORRECT_M,box_size=1,border=QUIET)
qr.add_data(PAYLOAD); qr.make(fit=False)
mat=qr.get_matrix()  # 33 x 33 including quiet zone
n=len(mat); assert n==33

# High-resolution PNG, rendered from the matrix with nearest-neighbour scaling.
total_px=round(total_mm/25.4*DPI)
arr=Image.new('1',(n,n),1); pix=arr.load()
for y,row in enumerate(mat):
    for x,bit in enumerate(row): pix[x,y]=0 if bit else 1
img=arr.resize((total_px,total_px),Image.Resampling.NEAREST).convert('RGB')
png=OUT/'SIH26034_QR_50mm_600dpi.png'; img.save(png,dpi=(DPI,DPI))

# Exact-size SVG.
svg=[]
svg.append(f'<svg xmlns="http://www.w3.org/2000/svg" width="{total_mm:.6f}mm" height="{total_mm:.6f}mm" viewBox="0 0 {total_mm:.6f} {total_mm:.6f}">')
svg.append('<rect width="100%" height="100%" fill="white"/>')
for y,row in enumerate(mat):
    for x,bit in enumerate(row):
        if bit:
            svg.append(f'<rect x="{x*module_mm:.6f}mm" y="{y*module_mm:.6f}mm" width="{module_mm:.6f}mm" height="{module_mm:.6f}mm" fill="black"/>')
svg.append('</svg>')
svgp=OUT/'SIH26034_QR_50mm.svg'; svgp.write_text('\n'.join(svg),encoding='utf-8')

# Exact vector PDF: no raster scaling ambiguity.
pdf=OUT/'SIH26034_QR_50mm_printable.pdf'
c=canvas.Canvas(str(pdf),pagesize=(210*mm,297*mm))
x0=(210-total_mm)/2*mm; y0=(297-total_mm)/2*mm+15*mm
for y,row in enumerate(mat):
    for x,bit in enumerate(row):
        if bit:
            c.rect(x0+x*module_mm*mm, y0+(n-1-y)*module_mm*mm, module_mm*mm, module_mm*mm, stroke=0, fill=1)
c.setFont('Helvetica-Bold',13); c.drawCentredString(105*mm,y0-10*mm,'SIH26034 — 50 mm QR CALIBRATION REFERENCE')
c.setFont('Helvetica',9); c.drawCentredString(105*mm,y0-16*mm,'QR symbol = exactly 50 mm × 50 mm at 100% print scale')
c.drawCentredString(105*mm,y0-21*mm,'Print at ACTUAL SIZE / 100%. Do not use Fit to Page or printer scaling.')
c.drawCentredString(105*mm,y0-26*mm,f'Payload: {PAYLOAD}')
c.save()
print(png); print(svgp); print(pdf)
