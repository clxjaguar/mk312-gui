#!/usr/bin/env python3
# Funscript2SRT by @cLxJaguar (2023)

import os, sys, argparse, json

def convert(filename, actionTimeout=2):
	filenameOut = os.path.splitext(filename)[0] + '.srt'
	f = open(filename, 'r')
	print("Converting \"%s\" to \"%s\"..." % (filename, filenameOut))
	data = json.load(f)
	for d in data:
		content = data[d]
		if type(content) == list:
			continue
		print('%s: %s' % (d, content))

	try:
		maxi = data['range']
	except:
		maxi = 100

	f_out = open(filenameOut, 'w')

	def mkSrtTimeStamp(ms):
		s = ms / 1000; ms%=1000
		m = s / 60; s%=60
		h = m / 60; m%=60
		return "%02d:%02d:%02d,%03d" % (h, m, s, ms)

	i = 1
	for action in data['actions']:
		try:
			nextAction = data['actions'][i]
		except:
			pass

		srt_timestamp_from = mkSrtTimeStamp(action['at'])
		srt_timestamp_to = mkSrtTimeStamp(min(action['at'] + actionTimeout*1000, nextAction['at']-10))
		content = "%g" % (action['pos'] / maxi)

		f_out.write("%d\n%s --> %s\n%s\n\n" % (i, srt_timestamp_from, srt_timestamp_to, content))
		i+=1

def main():
	if len(sys.argv) <= 1:
		print("Usage: %s <funscript input files>" % (sys.argv[0]))
		print("Convert the action and generate output srt files")
		exit(1)

	for filename in sys.argv[1:]:
		try:
			convert(filename)
		except Exception as e:
			print("Error:", str(e))

if __name__ == "__main__":
    main()
