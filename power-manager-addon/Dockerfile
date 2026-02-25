FROM python:3.12-alpine

# Install git for cloning the repo
RUN apk add --no-cache git

# Clone the Power Manager repository
# Change CACHE_BUST value to force fresh clone (Docker caches RUN layers)
ARG CACHE_BUST=1.0.10
RUN git clone https://github.com/galletn/PowerManager.git /opt/power-manager

WORKDIR /opt/power-manager

# Install Python dependencies
RUN pip install --no-cache-dir -r requirements.txt

# Copy run script
COPY run.sh /run.sh
RUN chmod +x /run.sh

CMD ["/run.sh"]
