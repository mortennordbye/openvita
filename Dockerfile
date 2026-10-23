# Build environment for the CVs: WeasyPrint renders HTML to PDF, poppler makes PNG previews.
# LibreOffice renders filled Word forms to PDF; Carlito, Caladea and Liberation stand in for
# Calibri, Cambria, Times New Roman and Arial with the same metrics.
# CV fonts come from each template via @font-face, not from the system.
# Pinned by digest; Dependabot bumps it.
FROM python:3.14-slim-trixie@sha256:0514bc76712d64f8bb48adcb95b1ab0d88c69fee95d62fe4c18ee948bee9b1e1

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
