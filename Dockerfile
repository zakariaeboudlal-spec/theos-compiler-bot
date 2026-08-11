FROM ubuntu:24.04

# Prevent interactive prompts during apt install
ENV DEBIAN_FRONTEND=noninteractive

# Install system dependencies
RUN apt-get update && apt-get install -y \
    git \
    curl \
    perl \
    clang \
    make \
    zip \
    unzip \
    unrar \
    p7zip-full \
    python3 \
    python3-pip \
    python3-dev \
    && rm -rf /var/lib/apt/lists/*

# Set up Theos
ENV THEOS=/opt/theos
RUN git clone --recursive https://github.com/theos/theos.git $THEOS

# Install iOS SDKs (including iPhoneOS16.5.sdk)
RUN git clone --depth 1 https://github.com/xybp888/iOS-SDKs.git /tmp/sdks \
    && mkdir -p $THEOS/sdks \
    && cp -r /tmp/sdks/*.sdk $THEOS/sdks/ \
    && rm -rf /tmp/sdks

# Set PATH for Theos
ENV PATH="$THEOS/bin:$PATH"

# Set up working directory for bot
WORKDIR /app

# Copy requirements and install python dependencies
COPY requirements.txt .
RUN pip3 install --no-cache-dir -r requirements.txt --break-system-packages

# Copy bot source code
COPY bot.py .

# Command to run the bot
CMD ["python3", "bot.py"]
