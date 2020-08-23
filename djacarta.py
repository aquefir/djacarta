#!/usr/bin/env python3
# -*- coding: utf-8 -*-

import curses

'''
high-level concept of curses editor program

what’s so special about this editor program?

- no commands ever involve holding keys for combos.
- no commands use ctrl, meta/alt, shift, or super/win keys.
- commands begin by pressing Tab, entering a string, and then Return.
- any in-progress command can be canceled using Backspace.

this is an approach similar to what is seen in power user editors like vi(m)
and emacs. only difference is, its much more keyboard-agnostic. its also
agnostic to sticky-key accessibility support patterns (no holding keys for
commands). this is very nice, but especially so on things like macbooks, which
throw ctrl/cmd for a loop, and may lack things like fn and esc keys on models
without a touchbar.

this is an early prototype written in python. eventually this software will be
written in ANSI C, once it is more feature complete. its made for the 640-wide
teletypes. it is simple, and it tries to stay as simple as possible while
being empowering to the user.

Commands list:
	`n` toggle nav mode. wasd moves the text cursor pos. ijkl moves viewport.
	`u-x` insert unicode codepoint x. leading zeroes not required.
	`o x` open file in path x. supports ~, but not shell vars.
	`t x` creates file in path x. supports ~, but not shell vars.
	`s x` save file in path x. supports ~, but not shell vars.
	`ss` quick save currently opened file.
	`cls` close the file, creating a new empty buffer in memory.
	`q` quit! it’s that easy.™
	`tabsz x` set tab size to x. valid values are nonnegative integers.

this is using the python curses wrapper for prototyping.
the application has a simple bar at the bottom, where the command buffer will
show up.
the rendering of everything in the window, including the file buffer, is
separated from the stage where input is obtained (getch).
some challenges in rendering include:
	1. rendering tabs manually, and accounting for their visual length
	2. bounding navigation to the edges of the buffer content
	3. syntax highlighting?
once these things are done, file io can be implemented.
'''

class State:
	def __init__(self):
		# curses window object
		self.win = curses.initscr()
		# keycode last pressed
		self.key = 0
		# the opened file, as a list of lines
		self.buffer = ['']
		# the path of the currently opened file
		self.openedfile = ''
		# the command buffer
		self.cmdbuffer = ''
		# switch for command mode
		self.cmdmode = False
		# switch for nav mode
		self.navmode = False
		# window dimensions
		self.win_w = 0
		self.win_h = 0
		# cursor position in buffer (wasd)
		# NOTE: bufcur_x is in literal chars, NOT visual chars!
		self.bufcur_x = 0
		self.bufcur_y = 0
		# nav mode’s sticky bufcur_x
		self.sticky_x = 0
		# window offset (ijkl)
		# NOTE: bufofs_x is in visual chars. account for hard tabs!
		self.bufofs_x = 0
		self.bufofs_y = 0
		# tab size (3)
		self.tabsz = 1
		self.globl = 0

def store_winsz(s):
	h, w = s.win.getmaxyx()
	s.win_w = w
	s.win_h = h

def ren_statbar(s):
	lhs = ''
	rhs = 'LF | T:' + str(s.tabsz) + ' '
	if s.cmdmode:
		lhs = ' command: ' + s.cmdbuffer
	else:
		lhs = ' -*- '
	if s.navmode:
		rhs = 'nav | ' + rhs
	else:
		rhs = 'wri | ' + rhs
	mid = ' ' * (s.win_w - len(lhs) - len(rhs) - 1)
	s.win.attron(curses.color_pair(3))
	s.win.addstr(s.win_h - 1, 0, lhs + mid + rhs)
	s.win.attroff(curses.color_pair(3))

def bufpos2vispos(text, tabsz, offs):
	i = 0
	ret = 0
	textlen = len(text)
	if offs > textlen:
		return textlen
	while i < offs:
		if text[i] == '\t':
			ret += tabsz
		else:
			ret += 1
		i += 1
	return ret

# this function does the inverse of the one above
def vispos2bufpos(text, tabsz, offs):
	ret = 0
	i = 0
	textlen = len(text)
	if offs > textlen:
		return textlen
	while i < offs:
		if i + tabsz < textlen:
			# this happens when the cursor is mid-character on a tab.
			# don’t count it
			pass
		elif text[i:i + tabsz] == ' ' * tabsz:
			ret += tabsz - 1
		else:
			ret += 1
		i += 1
	return ret

def move_cursor(s, wh):
	# moving the cursor properly is often nontrivial due to multi-character
	# width of tab characters. we need to use bufpos2vispos() to get a visual
	# x offset given a char offset, a tab size and a string that may contain tab
	# chars. this function wraps that lifter as a general ‘cursor mover’ function
	# valid values for wh are 'l', 'r', 'u' and 'd' for the four directions
	# NOTE: s.bufcur_x is kept in literal chars, not visual ones!
	oldvis = bufpos2vispos(s.buffer[s.bufcur_y], s.tabsz, s.bufcur_x)
	newvis = 0
	if wh == 'l':
		if s.bufcur_x > 0:
			s.bufcur_x -= 1
	elif wh == 'r':
		if s.bufcur_x < len(s.buffer[s.bufcur_y]):
			s.bufcur_x += 1
	elif wh == 'd':
		if s.bufcur_y + 1 >= len(s.buffer):
			# we’re at the end
			newvis = oldvis
		else:
			s.bufcur_y += 1
			s.bufcur_x = vispos2bufpos(s.buffer[s.bufcur_y], s.tabsz, oldvis)
	elif wh == 'u':
		if s.bufcur_y <= 0:
			# we’re at the beginning
			newvis = oldvis
		else:
			s.bufcur_y -= 1
			s.bufcur_x = vispos2bufpos(s.buffer[s.bufcur_y], s.tabsz, oldvis)

def render(s):
	# store window size
	store_winsz(s)
	# render status bar
	ren_statbar(s)
	# we need to define the boundaries of what we are rendering.
	# first get the length of the buffer for y bounding, then define our
	# limits using the window size.
	buflen = len(s.buffer)
	bufstart_y = s.bufofs_y
	bufend_y = s.bufofs_y + s.win_h
	# we may have scrollpast. account for this with a separate var and adjust
	# the actual bufend_y for the rendering loop
	blankendct_y = buflen - bufend_y
	bufend_y -= blankendct_y
	# to make x bounding vastly easier, we’re going to temporarily buffer the
	# visible lines with a string replaced version where hard tabs are
	# pre-rendered to simplify spacing for visuals.
	# the s.bufofs_x works in visual chars, so by expanding tabs ahead-of-time
	# it won’t throw off alignment when we go to render them
	renbuffer = s.buffer[bufstart_y:bufend_y]
	i = 0
	renbuflen = len(renbuffer)
	while i < renbuflen:
		renbuffer[i] = renbuffer[i].replace('\t', ' ' * s.tabsz)
		i += 1
	# move ahead with rendering the lines.
	i = 0
	blankline = ' ' * (s.win_w - 1)
	while i < s.win_h - 1:
		if i >= renbuflen:
			# this handles blank lines remaining
			s.win.addstr(i, 0, blankline)
		else:
			text = renbuffer[i][s.bufofs_x:s.bufofs_x + s.win_w]
			textlen = len(text)
			s.win.addstr(i, 0, text)
			if s.win_w - textlen > 0:
				s.win.addstr(i, textlen, ' ' * (s.win_w - textlen))
		i += 1
	# now, fix the cursor
	if s.cmdmode:
		s.win.move(s.win_h - 1, 10 + len(s.cmdbuffer))
	else:
		y = s.bufcur_y - s.bufofs_y
		s.globl = s.buffer[s.bufcur_y - bufstart_y]
		x = bufpos2vispos(s.buffer[s.bufcur_y - bufstart_y], s.tabsz, s.bufcur_x) - s.bufofs_x
		if y < 0 or x < 0:
			y = s.win_h - 1
			x = s.win_w - 1
		s.win.move(y, x)
	# refresh and done
	s.win.refresh()

def do_move_nav(s):
	if s.key == curses.KEY_UP:
		s.bufofs_y -= 1 if s.bufofs_y > 0 else 0
	elif s.key == curses.KEY_LEFT:
		s.bufofs_x -= 1 if s.bufofs_x > 0 else 0
	elif s.key == curses.KEY_DOWN:
		s.bufofs_y += 1 if len(s.buffer) - 1 > s.bufofs_y else 0
	elif s.key == curses.KEY_RIGHT:
		visible = False
		i = s.bufofs_y
		buflen = len(s.buffer)
		while i < s.bufofs_y + s.win_h - 1 and i < buflen:
			if s.buffer[i][s.bufofs_x + 1:] != '':
				visible = True
				break
			i += 1
		s.bufofs_x += 1 if visible else 0

def ins_chr(s):
	if s.bufcur_x == len(s.buffer[s.bufcur_y]):
		s.globl = s.key
		s.buffer[s.bufcur_y] += chr(s.key)
	else:
		lhs = s.buffer[s.bufcur_y][:s.bufcur_x]
		rhs = s.buffer[s.bufcur_y][s.bufcur_x:]
		s.buffer[s.bufcur_y] = lhs + chr(s.key) + rhs
	s.bufcur_x += 1
	if s.bufcur_x - s.bufofs_x > 79:
		s.bufofs_x += 1

def do_cmd(s):
	from os.path import expanduser, isfile
	cmd = s.cmdbuffer
	if cmd.startswith('u-'):
		cp = int(cmd[2:], 16)
		s.globl = cp
		if cp != None:
			s.key = cp
			ins_chr(s)
	elif cmd == 'n':
		s.navmode = not s.navmode
		s.sticky_x = s.bufcur_x
	elif cmd.startswith('o '):
		path = expanduser(cmd[2:])
		s.openedfile = path
		f = open(path, 'r')
		s.buffer = f.read().split('\n')
		f.close()
		s.bufofs_x = 0
		s.bufofs_y = 0
		s.bufcur_x = 0
		s.bufcur_y = 0
	elif cmd.startswith('t '):
		path = expanduser(cmd[2:])
		if not isfile(path):
			f = open(path, 'w')
			f.flush()
			f.close()
	elif cmd.startswith('s '):
		path = expanduser(cmd[2:])
		s.openedfile = path
		f = open(path, 'w')
		f.write('\n'.join(s.buffer) + '\n')
		f.flush()
		f.close()
	elif cmd == 'ss' and s.openedfile != '':
		f = open(s.openedfile, 'w')
		f.write('\n'.join(s.buffer) + '\n')
		f.flush()
		f.close()
	elif cmd.startswith('tabsz '):
		size = int(cmd[6:], 0)
		if size > 0 and size < 256:
			s.tabsz = size
	elif cmd == 'cls':
		s.openedfile = ''
		s.buffer = ['']
		s.bufofs_x = 0
		s.bufofs_y = 0
		s.bufcur_x = 0
		s.bufcur_y = 0
	elif cmd == 'q':
		return 1
	return 0

def mainloop(s):
	render(s)
	s.key = s.win.getch()
	if s.key == curses.ERR:
		return 0
	elif s.key == 9:
		if s.cmdmode:
			ins_chr(s)
			s.cmdmode = False
		else:
			s.cmdmode = True
	elif s.key == 10:
		# return/enter key
		if s.cmdmode:
			r = do_cmd(s)
			s.cmdmode = False
			s.cmdbuffer = ''
			if r:
				return 1
		elif not s.navmode:
			if s.bufcur_y < len(s.buffer) - 1:
				lhs = s.buffer[:s.bufcur_y + 1]
				rhs = s.buffer[s.bufcur_y + 1:]
				s.buffer = lhs + [''] + rhs
			else:
				s.buffer.append('')
			s.bufcur_y += 1
			s.bufcur_x = 0
	elif s.key == 127:
		# backspace/delete key (NOT the Del key)
		if s.cmdmode:
			s.cmdmode = False
			s.cmdbuffer = ''
		elif not s.navmode:
			if s.buffer == [''] or (s.bufcur_x == 0 and s.bufcur_y == 0):
				pass
			elif s.buffer[s.bufcur_y] == '':
				if s.bufcur_y < len(s.buffer) - 1:
					lhs = s.buffer[:s.bufcur_y]
					rhs = s.buffer[s.bufcur_y + 1:]
					s.buffer = lhs + rhs
				else:
					s.buffer = s.buffer[:-1]
				s.bufcur_y -= 1
				s.bufcur_x = len(s.buffer[s.bufcur_y])
			else:
				newx = s.bufcur_x - 1
				if s.bufcur_x == 0:
					newx = len(s.buffer[:s.bufcur_y - 1])
					line = s.buffer[s.bufcur_y - 1] + s.buffer[s.bufcur_y]
					lhs = s.buffer[:s.bufcur_y - 1]
					if lhs == []:
						lhs.append(line)
					else:
						lhs[-1] = line
					rhs = s.buffer[s.bufcur_y + 1:]
					s.buffer = lhs + rhs
					s.bufcur_y -= 1
					s.bufcur_x = newx
				elif s.bufcur_x < len(s.buffer[s.bufcur_y]):
					lhs = s.buffer[s.bufcur_y][:s.bufcur_x - 1]
					rhs = s.buffer[s.bufcur_y][s.bufcur_x:]
					s.buffer[s.bufcur_y] = lhs + rhs
				else:
					s.buffer[s.bufcur_y] = s.buffer[s.bufcur_y][:-1]
				s.bufcur_x = newx
	elif s.cmdmode:
		s.cmdbuffer += chr(s.key)
	elif s.key == curses.KEY_UP:
		move_cursor(s, 'u')
	elif s.key == curses.KEY_LEFT:
		move_cursor(s, 'l')
	elif s.key == curses.KEY_DOWN:
		move_cursor(s, 'd')
	elif s.key == curses.KEY_RIGHT:
		move_cursor(s, 'r')
	else:
		# normal typing mode
		ins_chr(s)
	return 0

def curses_init(s):
	# add some colours to the global curses library
	curses.start_color()
	curses.init_pair(1, curses.COLOR_CYAN, curses.COLOR_BLACK)
	curses.init_pair(2, curses.COLOR_RED, curses.COLOR_BLACK)
	curses.init_pair(3, curses.COLOR_BLACK, curses.COLOR_WHITE)
	# set up quirks
	s.win.nodelay(True)
	curses.cbreak()
	curses.noecho()
	s.win.keypad(True)

def curses_fini(s):
	s.win.keypad(False)
	curses.echo()
	curses.nocbreak()
	curses.endwin()

def main(args):
	from time import sleep
	s = None
	try:
		s = State()
		curses_init(s)
		while not mainloop(s):
			sleep(0.016)
	finally:
		curses_fini(s)
		print(s.globl)
	return 0

if __name__ == '__main__':
	from sys import argv, exit
	exit(main(argv))
