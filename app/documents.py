"""完整解析后才允许审核；不能读取的页面不视为空白证据。"""
import hashlib
import io
import logging
import zipfile
from pathlib import Path

from docx import Document
from docx.table import Table
from pypdf import PdfReader

MAX_BYTES = 8 * 1024 * 1024
MAX_CHARS = 24000

class DocumentFailure(Exception):
    pass


def parse_document(name: str, content: bytes):
    if not content or len(content) > MAX_BYTES:
        raise DocumentFailure('文件为空或超过 8 MB')
    suffix = Path(name).suffix.lower()
    blocks = []
    def add(text, location):
        text = text.strip()
        if text:
            blocks.append({'id': f'p{len(blocks)+1}', 'text': text, 'location': location})
    try:
        if suffix == '.txt':
            text = content.decode('utf-8-sig')
            if '\x00' in text or '\ufffd' in text:
                raise DocumentFailure('文本包含无效字符，请使用 UTF-8 文本')
            for i, line in enumerate(text.splitlines(), 1):
                add(line, f'第 {i} 行')
        elif suffix == '.pdf':
            logging.getLogger('pypdf').setLevel(logging.ERROR)
            pdf = PdfReader(io.BytesIO(content), strict=True)
            if pdf.is_encrypted:
                raise DocumentFailure('不支持加密 PDF')
            if len(pdf.pages) > 100:
                raise DocumentFailure('PDF 超过 100 页，未执行审核')
            for page_number, page in enumerate(pdf.pages, 1):
                text = page.extract_text()
                if not text or not text.strip():
                    raise DocumentFailure(f'第 {page_number} 页无法提取文本，可能为扫描页；未执行审核')
                for paragraph, line in enumerate(text.splitlines(), 1):
                    add(line, f'第 {page_number} 页，第 {paragraph} 段')
        elif suffix == '.docx':
            with zipfile.ZipFile(io.BytesIO(content)) as archive:
                if sum(x.file_size for x in archive.infolist()) > 32 * 1024 * 1024:
                    raise DocumentFailure('DOCX 解压内容超过限制')
                unsupported = [n for n in archive.namelist() if n.startswith(('word/footnotes', 'word/endnotes', 'word/header', 'word/footer'))]
                if unsupported:
                    raise DocumentFailure('DOCX 含页眉、页脚或脚注，请转为文本 PDF 以保留全部证据')
                xml = archive.read('word/document.xml')
                if b'<w:altChunk' in xml or b'<w:txbxContent' in xml or b'<w:del ' in xml or b'<w:ins ' in xml or b'<w:pict' in xml:
                    raise DocumentFailure('DOCX 含文本框、外部内容或未接受的修订，请转为文本 PDF')
            doc = Document(io.BytesIO(content))
            for i, block in enumerate(doc.iter_inner_content(), 1):
                if isinstance(block, Table):
                    for j, row in enumerate(block.rows, 1):
                        add('\t'.join(cell.text for cell in row.cells), f'第 {i} 块表格，第 {j} 行')
                else:
                    add(block.text, f'第 {i} 段')
            if doc.inline_shapes:
                raise DocumentFailure('DOCX 包含图片，无法确认是否有扫描证据，请提供文本 PDF')
        else:
            raise DocumentFailure('仅支持文本 PDF、DOCX 和 UTF-8 TXT')
    except DocumentFailure:
        raise
    except Exception:
        raise DocumentFailure('文件损坏或格式无法完整解析') from None
    total = sum(len(x['text']) for x in blocks)
    if not total:
        raise DocumentFailure('文件没有可审核的文本')
    if total > MAX_CHARS:
        raise DocumentFailure('文本超过当前 24000 字符审核上限，未截断或执行审核')
    return {'name': Path(name).name, 'sha256': hashlib.sha256(content).hexdigest(), 'blocks': blocks,
            'characters': total, 'complete': True}
