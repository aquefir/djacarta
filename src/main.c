/* -*- coding: utf-8 -*- */

#include <curses.h>
#include <uni/types/int.h>

struct state
{
	WINDOW* win;
	int key;
	struct uni_str** buf;
	ptri buf_sz;
	const char* opfile;
	struct uni_str* cmdbuf;
	unsigned cmdmode : 1;
	unsigned tabsz : 7;
	u32 win_w, win_h;
	u32 bufcur_x, bufcur_y;
	u32 bufofs_x, bufofs_y;
};

void curses_init( void )
{
	setlocale( LC_ALL, "en_US.UTF-8" );

	init_pair( 1, 231, 16 );
	initscr( );
	cbreak( );
	noecho( );
}

void curses_fini( void )
{
	echo( );
	nocbreak( );
	endwin( );
}

int main( int ac, char* av[] )
{
	setlocale( LC_ALL, "en_US.UTF-8" );
	initscr( );
	cbreak( );
	noecho( );

	return 0;
}
