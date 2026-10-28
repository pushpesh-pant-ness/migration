FROM python:3.12-slim
# Optional corporate TLS-inspection root CA (e.g. Netskope) for pip installs: put corporate-ca.pem next to this file.
# "Dockerfile" is listed so the COPY always matches at least one file.
COPY Dockerfile corporate-ca.pe[m] /tmp/ca/
RUN if [ -f /tmp/ca/corporate-ca.pem ]; then cp /tmp/ca/corporate-ca.pem /usr/local/share/ca-certificates/corporate-ca.crt; fi \
 && update-ca-certificates && rm -rf /tmp/ca
ENV PIP_CERT=/etc/ssl/certs/ca-certificates.crt
WORKDIR /app
COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt && useradd -m app
COPY app.py .
USER app
CMD ["gunicorn", "-b", "0.0.0.0:8080", "app:app"]
