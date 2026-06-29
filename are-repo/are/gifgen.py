from PIL import Image, ImageDraw
import imageio
import math
import os
import redis
from . import io
import logging
import tempfile
import shutil
import multiprocessing
from concurrent.futures import FIRST_COMPLETED, ProcessPoolExecutor, wait

def findnextindex(d, parentindex):
	return [key for key, value in d.items() if value[2] == parentindex]

def _neuron_base_from_filename(filename):
	return filename.split(".")[0]


def _process_one_file(args):
	textname, outputdirectoryPath, filename, skip_transfer = args

	white = (255, 255, 255)
	blue = (0, 0, 255)
	red = (255, 0, 0)
	green = (0, 128, 0)
	purple = (255, 0, 255)
	pink = (255, 192, 203)
	gray = (128, 128, 128)
	totalpixels = 62500

	try:
		f = open(textname, "r")
		try:
			lines = f.readlines()
		except UnicodeDecodeError:
			f.close()
			f = open(textname, "r", encoding='iso-8859-1')
			lines = f.readlines()
		f.close()
	except Exception as e:
		logging.exception('Error reading %s' % filename)
		raise

	dictionary = {}
	linecount = 0
	for line in lines:
		line = line.replace('  ', ' ')
		if line[0] == ' ':
			line = line[1:]
		if line[0] != '#' and line[0] != '\n':
			arr = line.split(' ')
			dictionary[int(arr[0])] = [(float(arr[2]), float(arr[3]), float(arr[4])), float(arr[5]), int(arr[6]), int(arr[1])]
			linecount += 1

	order = findnextindex(dictionary, 1)
	previouslen = 0
	lenrightnow = len(order)
	while len(order) < linecount - 1:
		for i in range(previouslen, lenrightnow):
			order.extend(findnextindex(dictionary, order[i]))
		previouslen = lenrightnow
		lenrightnow = len(order)
	order = [1] + order

	linesperdegree = math.ceil(linecount / 360)
	maxX = minX = maxY = minY = maxZ = minZ = 0
	for key, value in dictionary.items():
		if value[0][0] > maxX: maxX = value[0][0]
		if value[0][0] < minX: minX = value[0][0]
		if value[0][1] > maxY: maxY = value[0][1]
		if value[0][1] < minY: minY = value[0][1]
		if value[0][2] > maxZ: maxZ = value[0][2]
		if value[0][2] < minZ: minZ = value[0][2]

	maximumX = max(maxX, -minX, maxZ, -minZ)
	maximumY = max(maxY, -minY)
	ratiowh = 1.0 * maximumX / maximumY
	height = int(round(math.sqrt(totalpixels / ratiowh)))
	width = int(round(totalpixels / height))

	color_map = {1: (red, 5), 2: (gray, 1), 3: (green, 1), 4: (purple, 1), 6: (pink, 1), 7: (blue, 1)}
	hratio = (height - 5) / 2 / maximumY
	wratio = (width - 5) / 2 / maximumX

	tmpdir = tempfile.mkdtemp()
	try:
		for i in range(360):
			pdfname = os.path.join(tmpdir, "front" + str(i) + ".png")
			image = Image.new("RGB", (width, height), white)
			draw = ImageDraw.Draw(image)
			tempcounter = 0
			maxline = i * linesperdegree * 2
			for key in order:
				value = dictionary[key]
				if tempcounter <= maxline:
					if value[2] != -1:
						x2 = (width / 2) + value[0][0] * wratio
						y2 = (height / 2) - value[0][1] * hratio
						x1 = (width / 2) + dictionary[value[2]][0][0] * wratio
						y1 = (height / 2) - dictionary[value[2]][0][1] * hratio
						if dictionary[key][3] in color_map:
							c, lw = color_map[dictionary[key][3]]
							draw.line((x1, y1, x2, y2), c, lw)
					tempcounter += 1
			image.save(pdfname)

			cos2 = math.cos(0.0174533 * 2)
			sin2 = math.sin(0.0174533 * 2)
			for key, value in dictionary.items():
				x, y, z = value[0]
				value[0] = (z * sin2 + x * cos2, y, z * cos2 - x * sin2)

		images = [imageio.imread(os.path.join(tmpdir, "front" + str(i) + ".png")) for i in range(360)]
		imageio.mimsave(os.path.join(outputdirectoryPath, _neuron_base_from_filename(filename) + ".CNG.gif"), images)
	finally:
		shutil.rmtree(tmpdir, ignore_errors=True)

	if not skip_transfer:
		io.transfergif(_neuron_base_from_filename(filename))

	return filename


def _delete_recent_gifs(outputdirectoryPath, limit=100):
	if not os.path.isdir(outputdirectoryPath):
		return 0
	gifs = [
		os.path.join(outputdirectoryPath, item)
		for item in os.listdir(outputdirectoryPath)
		if item.lower().endswith(".gif")
	]
	gifs.sort(key=lambda path: os.path.getmtime(path), reverse=True)
	deleted = 0
	for path in gifs[:limit]:
		try:
			os.remove(path)
			deleted += 1
		except OSError:
			logging.exception("Could not delete resume GIF %s", path)
	return deleted


def _existing_output_bases(outputdirectoryPath):
	if not os.path.isdir(outputdirectoryPath):
		return set()
	return {
		item[:-8] if item.lower().endswith(".cng.gif") else item.rsplit(".", 1)[0]
		for item in os.listdir(outputdirectoryPath)
		if item.lower().endswith(".gif")
	}


def _push_gif_log(r, archive, message):
	key = "{}_gif_log".format(archive)
	r.rpush(key, message)
	r.ltrim(key, -80, -1)


def _stop_requested(r, archive):
	return r.get("{}_gif_stop".format(archive)) is not None


def gifgen(inputdirectoryPath, outputdirectoryPath, archive, skip_transfer=False, threads=12, resume=False):
	r = redis.Redis(
		host=os.getenv('REDIS_HOST', 'localhost'),
		port=int(os.getenv('REDIS_PORT', '6379')),
		db=int(os.getenv('REDIS_DB', '0')),
	)

	try:
		files = [
			item for item in os.listdir(inputdirectoryPath)
			if item.lower().endswith(".swc")
		]
		deleted = 0
		if resume:
			deleted = _delete_recent_gifs(outputdirectoryPath, 100)
			existing_bases = _existing_output_bases(outputdirectoryPath)
			files_to_process = [
				item for item in files
				if _neuron_base_from_filename(item) not in existing_bases
			]
			skipped = len(files) - len(files_to_process)
		else:
			files_to_process = files
			skipped = 0

		nFiles = len(files)
		threads = max(1, min(32, int(threads)))
		fileix = skipped
		r.delete("{}_gif_stop".format(archive))
		r.set("{}_gif_status".format(archive), 'running')
		r.set("{}_gif_progress".format(archive), fileix / nFiles * 100 if nFiles else 100)
		r.set("{}_gif_total".format(archive), nFiles)
		r.set("{}_gif_current".format(archive), fileix)
		r.delete("{}_gif_log".format(archive))
		_push_gif_log(
			r,
			archive,
			"Found {} SWC file(s); using {} thread(s)".format(nFiles, threads),
		)
		if resume:
			message = "Resume mode: deleted {} recent GIF(s), skipped {} existing GIF(s)".format(deleted, skipped)
			r.set("{}_gif_message".format(archive), message)
			_push_gif_log(r, archive, message)
		else:
			r.set("{}_gif_message".format(archive), '')

		_push_gif_log(r, archive, "Queued {} GIF file(s) to generate".format(len(files_to_process)))
		args = [(os.path.join(inputdirectoryPath, f), outputdirectoryPath, f, skip_transfer) for f in files_to_process]

		next_arg = 0
		stopped = False
		with ProcessPoolExecutor(max_workers=threads) as executor:
			running = set()
			while next_arg < len(args) and len(running) < threads:
				running.add(executor.submit(_process_one_file, args[next_arg]))
				next_arg += 1

			while running:
				done, running = wait(running, return_when=FIRST_COMPLETED)
				for future in done:
					result = future.result()
					fileix += 1
					message = "Completed {} ({}/{})".format(result, fileix, nFiles)
					r.set("{}_gif_progress".format(archive), fileix / nFiles * 100 if nFiles else 100)
					r.set("{}_gif_current".format(archive), fileix)
					r.set("{}_gif_message".format(archive), message)
					_push_gif_log(r, archive, message)

				if _stop_requested(r, archive):
					stopped = True
					r.set("{}_gif_status".format(archive), 'stopping')
					message = "Stopping after current work finishes ({}/{})".format(fileix, nFiles)
					r.set("{}_gif_message".format(archive), message)
					_push_gif_log(r, archive, message)
					continue

				while next_arg < len(args) and len(running) < threads:
					running.add(executor.submit(_process_one_file, args[next_arg]))
					next_arg += 1

		if stopped:
			message = "Stopped after completing {}/{} GIF file(s)".format(fileix, nFiles)
			r.set("{}_gif_status".format(archive), 'stopped')
			r.set("{}_gif_message".format(archive), message)
			_push_gif_log(r, archive, message)
		else:
			r.set("{}_gif_status".format(archive), 'success')
			message = "GIF generation complete: {}/{}".format(fileix, nFiles)
			r.set("{}_gif_message".format(archive), message)
			_push_gif_log(r, archive, message)

	except Exception as e:
		logging.exception('An error occurred during GIF generation of archive %s: %s: %s' % (archive, e.__class__, e))
		r = redis.Redis(
			host=os.getenv('REDIS_HOST', 'localhost'),
			port=int(os.getenv('REDIS_PORT', '6379')),
			db=int(os.getenv('REDIS_DB', '0')),
		)
		r.set("{}_gif_status".format(archive), 'error')
		r.set("{}_gif_message".format(archive), str(e))
		_push_gif_log(r, archive, "Error: {}".format(e))
		raise e
