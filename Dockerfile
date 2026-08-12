# syntax=docker/dockerfile:1

FROM python:3.12-alpine

# renovate: datasource=github-tags depName=FFmpeg/FFmpeg
ARG FFMPEG_VERSION=7.0

LABEL org.opencontainers.image.source="https://github.com/sasanjac/abs-library-tools"
LABEL org.opencontainers.image.description="Audiobook library tools - converts audio files into chaptered .m4b audiobooks"
LABEL org.opencontainers.image.licenses="MIT"

# copy the uv binary from the official distroless image
COPY --from=ghcr.io/astral-sh/uv:0.9.7 /uv /usr/local/bin/uv

# build ffmpeg (with non-free libfdk-aac) and install its runtime dependencies
RUN \
	echo "**** enable edge/testing for fdk-aac-dev ****" && \
	echo "http://dl-cdn.alpinelinux.org/alpine/edge/testing" >> /etc/apk/repositories && \
	echo "**** install build packages ****" && \
	apk add --no-cache --virtual=build-dependencies \
		binutils \
		build-base \
		ca-certificates \
		cmake \
		fdk-aac-dev \
		freetype-dev \
		g++ \
		gcc \
		jpeg-dev \
		libass-dev \
		libc-dev \
		libgcc \
		libogg-dev \
		libpng-dev \
		libtheora-dev \
		libvorbis-dev \
		libvpx-dev \
		make \
		musl-dev \
		nasm \
		openjpeg-dev \
		openssl \
		openssl-dev \
		opus-dev \
		pcre \
		pcre-dev \
		pkgconf \
		pkgconfig \
		wget \
		x264-dev \
		x265-dev \
		yasm-dev \
		zlib-dev && \
	echo "**** install runtime packages ****" && \
	apk add --no-cache \
		fdk-aac \
		jpeg \
		lame \
		libass \
		libpng \
		libtheora \
		libvorbis \
		libvpx \
		libwebp \
		libxcb \
		openjpeg \
		opus \
		x264 \
		x264-libs \
		x265 && \
	echo "**** compiling ffmpeg ${FFMPEG_VERSION} ****" && \
	cd /tmp && \
	wget "http://ffmpeg.org/releases/ffmpeg-${FFMPEG_VERSION}.tar.gz" && \
	tar zxf "ffmpeg-${FFMPEG_VERSION}.tar.gz" && \
	cd "/tmp/ffmpeg-${FFMPEG_VERSION}" && \
	./configure \
		--enable-gpl \
		--enable-nonfree \
		--enable-small \
		--enable-libmp3lame \
		--enable-libx264 \
		--enable-libx265 \
		--enable-libvpx \
		--enable-libtheora \
		--enable-libvorbis \
		--enable-libopus \
		--enable-libfdk-aac \
		--enable-libass \
		--enable-libwebp \
		--enable-postproc \
		--enable-libfreetype \
		--enable-openssl \
		--disable-debug && \
	make -j"$(nproc)" && \
	make install && \
	echo "**** cleanup ****" && \
	apk del --purge build-dependencies && \
	rm -rf \
		/root/.cache \
		/tmp/*

# install the application into a self-contained virtual environment at build time
ENV UV_COMPILE_BYTECODE=1 \
	UV_LINK_MODE=copy \
	UV_PYTHON_PREFERENCE=only-system \
	UV_PROJECT_ENVIRONMENT=/app/.venv \
	PATH="/app/.venv/bin:${PATH}"

WORKDIR /app

# install dependencies first for better layer caching ...
RUN --mount=type=cache,target=/root/.cache/uv \
	--mount=type=bind,source=pyproject.toml,target=pyproject.toml \
	--mount=type=bind,source=uv.lock,target=uv.lock \
	uv sync --frozen --no-install-project --no-dev

# ... then the project source itself
COPY pyproject.toml uv.lock README.md LICENSE ./
COPY src ./src
RUN --mount=type=cache,target=/root/.cache/uv \
	uv sync --frozen --no-dev

# run as an unprivileged user
RUN addgroup -S app && \
	adduser -S -G app -h /app app && \
	mkdir -p /data/import /data/export && \
	chown -R app:app /app /data

USER app

VOLUME /data/import /data/export

CMD ["python", "/app/src/alt/daemons.py"]
