"""Pull plain text out of an uploaded PDF contract."""
import io
import re

from pypdf import PdfReader
from pypdf.errors import PdfReadError

MAX_BYTES = 5 * 1024 * 1024
MAX_PAGES = 30


class PdfTextError(ValueError):
    """A problem the user can fix (shown to them as-is)."""


def pdf_to_text(data: bytes) -> str:
    if len(data) > MAX_BYTES:
        raise PdfTextError("This PDF is larger than 5 MB. Please upload a smaller file.")
    try:
        reader = PdfReader(io.BytesIO(data))
        if reader.is_encrypted:
            try:
                reader.decrypt("")
            except Exception:
                raise PdfTextError("This PDF is password-protected. Remove the password and try again.")
        if len(reader.pages) > MAX_PAGES:
            raise PdfTextError(f"This PDF has more than {MAX_PAGES} pages. Please upload just the contract.")
        pages = [page.extract_text() or "" for page in reader.pages]
    except PdfTextError:
        raise
    except (PdfReadError, ValueError, KeyError, TypeError) as error:
        raise PdfTextError(f"This file couldn't be read as a PDF ({error.__class__.__name__}).")

    text = "\n\n".join(pages)
    text = text.replace(" ", " ")
    text = re.sub(r"(\w)-\n(\w)", r"\1\2", text)          # join words split across lines
    text = re.sub(r"[ \t]+", " ", text)                    # collapse runs of spaces
    text = "\n".join(line.strip() for line in text.splitlines())
    text = re.sub(r"\n{3,}", "\n\n", text).strip()         # at most one blank line
    # Re-join sentences that the PDF wrapped onto two lines ("billing\ncontact" -> "billing contact").
    text = re.sub(r"(?<=[^\s.:;!?)\]])\n(?=[a-z\"$])", " ", text)
    # Put a blank line before numbered section headings ("2. Fees") so sections stand apart.
    text = re.sub(r"\n(?=\d{1,2}\.\s+[A-Z])", "\n\n", text)

    if len(text) < 50:
        raise PdfTextError("No text was found in this PDF. It may be a scanned image. "
                           "Please paste the contract text instead.")
    return text
