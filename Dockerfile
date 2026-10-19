# Build environment for the CVs: WeasyPrint renders HTML to PDF, poppler makes PNG previews.
# LibreOffice renders filled Word forms to PDF; Carlito, Caladea and Liberation stand in for
# Calibri, Cambria, Times New Roman and Arial with the same metrics.
# CV fonts come from each template via @font-face, not from the system.
FROM python:3.14-slim-trixie

RUN apt-get update \
 && apt-get install -y --no-install-recommends libpango-1.0-0 libpangoft2-1.0-0 libharfbuzz-subset0 poppler-utils fontconfig \
    libreoffice-writer-nogui fonts-crosextra-carlito fonts-crosextra-caladea fonts-liberation \
 && rm -rf /var/lib/apt/lists/*

RUN pip install --no-cache-dir weasyprint==70.0

ENV HOME=/tmp
WORKDIR /work
