FROM python:3.12-alpine

# Install git for cloning the repo
RUN apk add --no-cache git

# Clone the Power Manager repository
# Docker caches RUN layers - changing the echo string forces a fresh clone
RUN echo "cache-bust-1.0.26" && git clone https://github.com/galletn/PowerManager.git /opt/power-manager

WORKDIR /opt/power-manager

# Install Python dependencies
RUN pip install --no-cache-dir -r requirements.txt

# Copy run script
COPY run.sh /run.sh
RUN chmod +x /run.sh

CMD ["/run.sh"]
