# Build environment for the CVs: WeasyPrint renders HTML to PDF, poppler makes PNG previews.
# LibreOffice renders filled Word forms to PDF; Carlito, Caladea and Liberation stand in for
# Calibri, Cambria, Times New Roman and Arial with the same metrics.
# CV fonts come from each template via @font-face, not from the system.
# Pinned by digest; Dependabot bumps it.
FROM python:3.15-slim-trixie@sha256:65a65fc7b30b06cb6df4930fd4650697cb23f4c2698ab81fc87e4b031bc36928

RUN apt-get update \
 && apt-get install -y --no-install-recommends libpango-1.0-0 libpangoft2-1.0-0 libharfbuzz-subset0 poppler-utils fontconfig \
    libreoffice-writer-nogui fonts-crosextra-carlito fonts-crosextra-caladea fonts-liberation \
 && rm -rf /var/lib/apt/lists/*

# pip is only needed to build the image; removing it also removes the libraries it vendors
# (urllib3, msgpack, setuptools), which nothing here uses.
RUN pip install --no-cache-dir weasyprint==70.0 \
 && python3 -m pip uninstall -y pip

ENV HOME=/tmp
WORKDIR /work
