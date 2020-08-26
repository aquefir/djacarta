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
written in ANSI C, once it is more feature complete. its made for the 80-wide
teletypes. it is simple, and it tries to stay as simple as possible while
being empowering to the user.

Commands list:
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
		self.tabsz = 3
		self.globl = 0

import re

expr_commentopen = re.compile(r'(/\*)')
expr_commentclos = re.compile(r'(\*/)')
expr_keyword = re.compile(r'\b(break|case|continue|default|do|else|enum|for|goto|if|return|sizeof|struct|switch|typedef|while|union)\b')
expr_function = re.compile(r'\b(([A-Za-z_][A-Za-z0-9_]*)(?=\s*\())')
expr_type = re.compile(r'\b(char|const|double|extern|float|inline|int|long|register|restrict|short|signed|static|unsigned|void|volatile)\b')
expr_numeric = re.compile(r"\b(((0(x|X)[0-9a-fA-F]([0-9a-fA-F']*[0-9a-fA-F])?)|(0(b|B)[01]([01']*[01])?)|(([0-9]([0-9']*[0-9])?\.?[0-9]*([0-9']*[0-9])?)|(\.[0-9]([0-9']*[0-9])?))((e|E)(\+|-)?[0-9]([0-9']*[0-9])?)?)(L|l|UL|ul|u|U|F|f|ll|LL|ull|ULL)?)\b")
expr_symbol = re.compile(r'(%=?|\+[\+=]?|-[\-=]?|\*=?|/=?|&[&=]?|\|[\|=]?|\^=?|<<=?|>>=?|!=?|==?|<=?|>=?|[\?:;~\[\]\{\}\(\),\.])')
expr_string = re.compile(r'(?!\\)(")(([^"]|\\")*)(")')
expr_char = re.compile(r"(?!\\)(')(\\['\\]|.)(')")
expr_constants = re.compile(r'(NULL|TRUE|FALSE|true|false)')

# this function decorates the buffer with non-printing ASCII chars denoting
# colour groups to use
# we use \032 (ASCII ESCAPE) followed by a fixed size 1 byte number containing
# the colour group number. \032\032 terminates a color group
def decor_syntax(line):
	line = expr_commentopen.sub('\032\012\\1', line)
	line = expr_commentclos.sub('\\1\032\031', line)
	line = expr_string.sub('\032\007\\1\032\032\032\006\\2\032\031\032\007\\4\032\032', line)
	line = expr_char.sub('\032\007\\1\032\032\032\006\\2\032\031\032\007\\3\032\032', line)
	line = expr_symbol.sub('\032\013\\1\032\032', line)
	line = expr_numeric.sub('\032\010\\1\032\032', line)
	line = expr_keyword.sub('\032\003\\1\032\032', line)
	line = expr_type.sub('\032\005\\1\032\032', line)
	line = expr_constants.sub('\032\011\\1\032\032', line)
	line = expr_function.sub('\032\004\\1\032\032', line)
	return line

def store_winsz(s):
	h, w = s.win.getmaxyx()
	s.win_w = w
	s.win_h = h

def ren_statbar(s):
	lhs = ''
	rhs = 'X:' + str(s.bufcur_x) + ' Y:' + str(s.bufcur_y) + ' | LF | T:' + str(s.tabsz) + ' '
	if s.cmdmode:
		lhs = ' command: ' + s.cmdbuffer
	else:
		lhs = ' -*- '
	mid = ' ' * (s.win_w - len(lhs) - len(rhs) - 1)
	s.win.attron(curses.color_pair(2))
	s.win.addstr(s.win_h - 1, 0, lhs + mid + rhs)
	s.win.attroff(curses.color_pair(2))

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
		if bufpos2vispos(s.buffer[s.bufcur_y], s.tabsz, s.bufcur_x) < s.bufofs_x:
			s.bufofs_x = bufpos2vispos(s.buffer[s.bufcur_y], s.tabsz, s.bufcur_x)
	elif wh == 'r':
		if s.bufcur_x < len(s.buffer[s.bufcur_y]):
			s.bufcur_x += 1
		if bufpos2vispos(s.buffer[s.bufcur_y], s.tabsz, s.bufcur_x) >= s.bufofs_x + s.win_w:
			s.bufofs_x = bufpos2vispos(s.buffer[s.bufcur_y], s.tabsz, s.bufcur_x)
	elif wh == 'd':
		if s.bufcur_y + 1 >= len(s.buffer):
			# we’re at the end
			newvis = oldvis
		else:
			s.bufcur_y += 1
			s.bufcur_x = vispos2bufpos(s.buffer[s.bufcur_y], s.tabsz, oldvis)
		if s.bufcur_y >= s.bufofs_y + s.win_h - 1:
			s.bufofs_y += 1
	elif wh == 'u':
		if s.bufcur_y <= 0:
			# we’re at the beginning
			newvis = oldvis
		else:
			s.bufcur_y -= 1
			s.bufcur_x = vispos2bufpos(s.buffer[s.bufcur_y], s.tabsz, oldvis)
		if s.bufcur_y < s.bufofs_y:
			s.bufofs_y -= 1

def render(s):
	# store window size
	store_winsz(s)
	# render status bar
	ren_statbar(s)
	s.win.attron(curses.color_pair(1))
	# we need to define the boundaries of what we are rendering.
	# first get the length of the buffer for y bounding, then define our
	# limits using the window size.
	buflen = len(s.buffer)
	bufstart_y = s.bufofs_y
	bufend_y = s.bufofs_y + s.win_h - 1
	# we may have scrollpast. account for this with a separate var and adjust
	# the actual bufend_y for the rendering loop
	blankendct_y = -(buflen - bufend_y)
	bufend_y -= blankendct_y
	# to make x bounding vastly easier, we’re going to temporarily buffer the
	# visible lines with a string replaced version where hard tabs are
	# pre-rendered to simplify spacing for visuals.
	# the s.bufofs_x works in visual chars, so by expanding tabs ahead-of-time
	# it won’t throw off alignment when we go to render them
	renbuffer = s.buffer[bufstart_y:bufend_y]
	s.globl = s.buffer
	i = 0
	renbuflen = len(renbuffer)
	while i < renbuflen:
		renbuffer[i] = renbuffer[i].replace('\t', ' ' * s.tabsz)
		i += 1
	# move ahead with rendering the lines.
	i = 0
	blankline = ' ' * (s.win_w)
	exclusive = False
	while i < s.win_h - 1:
		if i >= renbuflen:
			# this handles blank lines remaining
			s.win.addstr(i, 0, blankline)
		else:
			text = renbuffer[i][s.bufofs_x:s.bufofs_x + s.win_w]
			textlen = len(text)
			coltext = decor_syntax(text)
			# counter incl. col codes
			j = 0
			# visual text pos
			i2 = 0
			activgrp = 0
			coltextlen = len(coltext)
			while j < coltextlen:
				if j + 1 < coltextlen and coltext[j] == '\032':
					grp = int.from_bytes(bytes(coltext[j + 1], 'utf-8'), 'little')
					if not exclusive and grp == 0o032 and activgrp > 0:
						s.win.attroff(curses.color_pair(activgrp))
						s.win.attron(curses.color_pair(1))
						activgrp = 0
					elif grp == 0o031:
						exclusive = False
						s.win.attroff(curses.color_pair(activgrp))
						s.win.attron(curses.color_pair(1))
						activgrp = 0
					elif not exclusive:
						s.win.attroff(curses.color_pair(1))
						s.win.attron(curses.color_pair(grp))
						activgrp = grp
						if grp == 10 or grp == 6:
							exclusive = True
					j += 2
				else:
					s.globl = bytes(coltext, 'utf-8')
					s.win.addstr(i, i2, coltext[j])
					j += 1
					i2 += 1
			if s.win_w - textlen > 0:
				s.win.addstr(i, textlen, ' ' * (s.win_w - textlen))
		i += 1
	# now, fix the cursor
	if s.cmdmode:
		s.win.move(s.win_h - 1, 10 + len(s.cmdbuffer))
	else:
		y = s.bufcur_y - s.bufofs_y
		if y >= s.win_h - 1:
			y -= 1
		x = bufpos2vispos(s.buffer[s.bufcur_y - bufstart_y], s.tabsz, s.bufcur_x) - s.bufofs_x
		if y < 0 or x < 0:
			y = s.win_h - 1
			x = s.win_w - 1
		s.win.move(y, x)
	s.win.attroff(curses.color_pair(1))
	# refresh and done
	s.win.refresh()

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
		if cp != None:
			s.key = cp
			ins_chr(s)
	elif cmd == 'h':
		s.bufcur_x = 0
		s.bufofs_x = 0
	elif cmd == 'e':
		s.bufcur_x = len(s.buffer[s.bufcur_y])
		s.bufofs_x = bufpos2vispos(s.buffer[s.bufcur_y], s.tabsz, s.bufcur_x)
	elif cmd == 'va':
		# vertically align
		s.bufofs_y = s.bufcur_y
	elif cmd == 'ha':
		# horizontally align
		s.bufofs_x = bufpos2vispos(s.buffer[s.bufcur_y], s.tabsz, s.bufcur_x)
	elif cmd == 'pu':
		# page up
		if s.bufcur_y - (s.win_h - 1) >= 0:
			s.bufofs_y -= s.win_h - 1
			s.bufcur_y -= s.win_h - 1
		else:
			s.bufofs_y = 0
			s.bufcur_y = 0
	elif cmd == 'pd':
		# page down
		bufferlen = len(s.buffer)
		if s.bufcur_y + s.win_h - 1 <= bufferlen:
			s.bufofs_y += s.win_h - 1
			s.bufcur_y += s.win_h - 1
		else:
			s.bufofs_y = bufferlen - 1
			s.bufcur_y = bufferlen - 1
	elif cmd.startswith('g '):
		# goto line number
		num = int(cmd[2:], 0)
		if num < len(s.buffer):
			s.bufcur_y = num
			s.bufofs_y = s.bufcur_y
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
		else:
			if s.bufcur_y < len(s.buffer) - 1:
				if s.bufcur_x < len(s.buffer[s.bufcur_y]):
					curline = s.buffer[s.bufcur_y]
					lhs = s.buffer[:s.bufcur_y + 1]
					lhs[-1] = curline[:s.bufcur_x]
					rhs = s.buffer[s.bufcur_y:]
					rhs[0] = curline[s.bufcur_x:]
					s.buffer = lhs + rhs
				else:
					s.buffer.insert(s.bufcur_y + 1, '')
			else:
				s.buffer.append('')
			s.bufcur_y += 1
			s.bufcur_x = 0
	elif s.key == 27:
		# escape key
		s.cmdmode = False
		s.cmdbuffer = ''
	elif s.key == 330:
		# Del key
		linelen = len(s.buffer[s.bufcur_y])
		buflen = len(s.buffer)
		if s.buffer == [''] or (s.bufcur_x >= linelen and s.bufcur_y >= buflen - 1):
			pass
		# del at end of a line
		elif s.bufcur_x >= linelen and s.bufcur_y + 1 < buflen:
			s.buffer[s.bufcur_y] += s.buffer[s.bufcur_y + 1]
			del s.buffer[s.bufcur_y + 1]
			buflen -= 1
		else:
			lhs = s.buffer[s.bufcur_y][:s.bufcur_x]
			rhs = s.buffer[s.bufcur_y][s.bufcur_x + 1:]
			s.buffer[s.bufcur_y] = lhs + rhs
	elif s.key == 127:
		# backspace/delete key (NOT the Del key)
		if s.cmdmode:
			s.cmdbuffer = s.cmdbuffer[:-1]
		else:
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
					newx = len(s.buffer[s.bufcur_y - 1])
					line = s.buffer[s.bufcur_y - 1] + s.buffer[s.bufcur_y]
					lhs = s.buffer[:s.bufcur_y]
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
	elif s.key < 256:
		# normal typing mode
		ins_chr(s)
	return 0

def curses_init(s):
	# add some colours to the global curses library
	curses.start_color()
	# Default
	curses.init_pair(1, 231, 16)
	# Inverted (statbar)
	curses.init_pair(2, 16, 231)
	## THEME COLOURS
	# keyword (blue)
	curses.init_pair(3, 27, 16)
	# function (puse)
	curses.init_pair(4, 76, 16)
	# type (teal)
	curses.init_pair(5, 42, 16)
	# string contents (red)
	curses.init_pair(6, 202, 16)
	# string specials (light red)
	curses.init_pair(7, 209, 16)
	# numeric literals (light blue)
	curses.init_pair(8, 69, 16)
	# constants (golden yellow)
	curses.init_pair(9, 220, 16)
	# comments (grey)
	curses.init_pair(10, 240, 16)
	# symbols (silver)
	curses.init_pair(11, 250, 16)

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
		#print(s.globl)
	return 0

if __name__ == '__main__':
	from sys import argv, exit
	exit(main(argv))
