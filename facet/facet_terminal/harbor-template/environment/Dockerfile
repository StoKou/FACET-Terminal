FROM ubuntu:22.04

ENV DEBIAN_FRONTEND=noninteractive

RUN apt-get update && \
    apt-cache policy python3 python3-pip python3-venv git | sed -n '1,160p' && \
    rm -rf /var/lib/apt/lists/*

WORKDIR /task_file
COPY task_file/ /task_file/
