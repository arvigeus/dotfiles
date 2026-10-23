# OCR integration

The module installs Arch's `gimagereader-qt` and Tesseract with eng/bul/vie models.
gImageReader discovers installed recognition languages through Tesseract and owns
its own desktop registration, text editor and export workflow. Dotfiles do not
change the default image/PDF applications or deploy a custom recognition wrapper.

PDF-specific editing and draft handling live in `media/tools/pdf`; its OCRmyPDF
PDF/A conversion runs with recognition disabled.
