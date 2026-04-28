# Get the base Ubuntu image from Docker Hub
FROM ubuntu:18.04

# Update apps on the base image
RUN DEBIAN_FRONTEND=noninteractive
RUN apt-get -y update && apt-get install -y g++ build-essential python3-pip python3-dev apt-utils default-jre-headless
RUN apt-get update

# Copy the current folder which contains C++ source code to the Docker image under /usr/src
COPY requirements.txt /app/

WORKDIR /app

RUN pip3 install --no-cache-dir -r /app/requirements.txt

# copy files required for the app to run
COPY app.py /app/
COPY *.cpp /app/
COPY *.h /app/
COPY Makefile /app/
ADD java /app/java/
RUN mkdir -p /app/des
RUN mkdir -p /app/input
RUN mkdir -p /app/output
RUN mkdir -p /app/pdg


# Use Clang to compile source files



# Run the output program from the previous step
#CMD ["./main"]

ENV FLASK_APP=app.py
ENV LC_ALL=C.UTF-8
ENV LANG=C.UTF-8


# tell the port number the container should expose
EXPOSE 5000

CMD make; flask run --host 0.0.0.0