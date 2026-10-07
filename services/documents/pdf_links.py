"""Extract external hyperlinks from a PDF while retaining their source pages."""
from urllib.parse import urldefrag, urljoin, urlparse


def extract_pdf_links(content, base_url=None):
    import pymupdf

    found = []
    with pymupdf.open(stream=content, filetype="pdf") as document:
        for page_number, page in enumerate(document, start=1):
            for link in page.get_links():
                uri = link.get("uri")
                if not uri:
                    continue
                absolute = urljoin(base_url or "", uri)
                parsed = urlparse(absolute)
                if parsed.scheme not in {"http", "https"} or not parsed.hostname:
                    continue
                absolute = urldefrag(absolute).url
                if base_url and absolute == urldefrag(base_url).url:
                    continue
                rect = link.get("from")
                try:
                    label = page.get_textbox(rect).strip() if rect else ""
                except (TypeError, ValueError):
                    label = ""
                found.append({"url": absolute, "page_number": page_number, "label": label[:500]})
    return found
