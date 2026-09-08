"""Synthetic audit text and minimal text PDFs. No student records or copied reports."""

def audit_text(program='Computer Science',code='ASBSCS',catalog='2026-2027',date='08/20/2026',extra=''):
    return f'''Arizona State University Degree Audit
Evaluated Program: {program}
Program Code {code} Catalog Year {catalog}
Prepared On {date} 10:00 AM
Campus: Tempe
{program.upper()} MAJOR REQUIREMENTS
1) CSE 110 - 4 hours
NEEDS: 4.00 HOURS
COURSE LIST: CSE 110
2) Technical elective - 3 hours
NEEDS: 3.00 HOURS
COURSE LIST: CSE 205 OR CSE 240
{extra}
'''

def pdf(text, pages=1):
    """Small, standards-compliant PDF fixture using an uncompressed text stream."""
    escaped=lambda t:t.replace('\\','\\\\').replace('(','\\(').replace(')','\\)')
    stream='BT /F1 10 Tf 14 TL 40 760 Td '+ ' T* '.join(f'({escaped(line)}) Tj' for line in text.splitlines())+' ET'
    content=stream.encode('latin1')
    objects=[b'<< /Type /Catalog /Pages 2 0 R >>',f'<< /Type /Pages /Count {pages} /Kids ['.encode()+b' '.join(f'{5+i} 0 R'.encode() for i in range(pages))+b'] >>',b'<< /Type /Font /Subtype /Type1 /BaseFont /Helvetica >>',f'<< /Length {len(content)} >>\nstream\n'.encode()+content+b'\nendstream']
    objects += [b'<< /Type /Page /Parent 2 0 R /MediaBox [0 0 612 792] /Resources << /Font << /F1 3 0 R >> >> /Contents 4 0 R >>']*pages
    result=bytearray(b'%PDF-1.4\n');offsets=[0]
    for i,obj in enumerate(objects,1):
        offsets.append(len(result));result.extend(f'{i} 0 obj\n'.encode()+obj+b'\nendobj\n')
    xref=len(result);result.extend(f'xref\n0 {len(objects)+1}\n0000000000 65535 f \n'.encode())
    for offset in offsets[1:]:result.extend(f'{offset:010d} 00000 n \n'.encode())
    result.extend(f'trailer\n<< /Size {len(objects)+1} /Root 1 0 R >>\nstartxref\n{xref}\n%%EOF'.encode())
    return bytes(result)
