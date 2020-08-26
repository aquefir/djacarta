/* -*- coding: utf-8 -*- */
/****************************************************************************\
 *                                 DjaCarta                                 *
 *                                                                          *
 *                      Copyright © 2019-2020 Aquefir                       *
 *                       Released under BSD-2-Clause.                       *
\****************************************************************************/

#include <locale.h>
#include <termbox.h>
#include <uni/types/int.h>

typedef u16 vwinid_t;

struct win
{
	s32 x, y, z;
	u32 w, h;
	unsigned bgcol : 8;
	unsigned fgcol : 8;
	unsigned visible : 1;
	unsigned bordered : 1;
	unsigned titled : 1;
	unsigned closable : 1;
	const char* title;
	u8* content;
};

struct state
{
	u32 term_w, term_h;
};

void ui_init( void )
{
	setlocale( LC_ALL, "C" );
	tb_init( );
}

void ui_fini( void )
{
	tb_shutdown( );
}

int main( int ac, char* av[] )
{
	ui_init( );

	return 0;
}
