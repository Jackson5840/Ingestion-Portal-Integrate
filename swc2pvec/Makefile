# Makefile for Pvec generation code
# Author: Bengt Ljungquist bljungqu@gmu.edus
 
# *****************************************************
# Variables to control Makefile operation
 
CC = g++
CFLAGS = -Wall -g
 
# ****************************************************
# Targets needed to bring the executable up to date
 
main: main.o Graph.o FileFun.o vectorization
	$(CC) $(CFLAGS) -o main main.o Graph.o FileFun.o
 
# The main.o target can be written more simply
 
main.o: main.cpp Graph.h FileFun.h
	$(CC) $(CFLAGS) -c main.cpp
 
Graph.o: Graph.h
 
FileFun.o: FileFun.h

vectorization: vectorization.cpp
	$(CC) $(CFLAGS) -o vectorization vectorization.cpp