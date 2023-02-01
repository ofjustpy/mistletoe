"""
Ofjustpy renderer for mistletoe.
"""

import html
import re
from itertools import chain
from urllib.parse import quote
from addict import Dict
from mistletoe import block_token
from mistletoe import span_token
from mistletoe.block_token import HTMLBlock
from mistletoe.span_token import HTMLSpan
from mistletoe.base_renderer import BaseRenderer
from mistletoe.ofjustpy_renderer_helper import openCtx, openCloseCtx, captureViewDirective, renderDictOrHC
from inspect import getmembers, isfunction
import ofjustpy as oj

class OfjustpyRenderer(BaseRenderer):
    """
    HTML renderer class.

    See mistletoe.base_renderer module for more info.
    """
    def __init__(self, *extras, **kwargs):
        """
        Args:
            extras (list): allows subclasses to add even more custom tokens.
        """
        self._suppress_ptag_stack = [False]
        super().__init__(*chain((HTMLBlock, HTMLSpan), extras))
        # html.entities.html5 includes entitydefs not ending with ';',
        # CommonMark seems to hate them, so...
        self._stdlib_charref = html._charref
        _charref = re.compile(r'&(#[0-9]+;'
                              r'|#[xX][0-9a-fA-F]+;'
                              r'|[^\t\n\f <&#;]{1,32};)')
        html._charref = _charref
        self.parsing_in_meta_mode = False
        # used to assign keys for oj element
        self.key_cursor = 1
        md_view_handlers_module = kwargs.pop('md_view_handlers', None)

        self.session_manager = kwargs.pop('session_manager', None)
        # document_key is the key for the stub generated from
        # the document
        self.document_key = kwargs.pop('document_key', None)

        if md_view_handlers_module:
            md_view_handlers_module.session_manager = self.session_manager
            self.mdview_funclookup = dict(getmembers(md_view_handlers_module, isfunction))
        else:
            self.mdview_funclookup =  {}
        #print ("mdview_funclookup = ", self.mdview_funclookup)
        #mditem_handler: gets populated from view directive in md file
        self.mditem_view_handlers = {}

        # stack of mditem context
        # its necessary that all stubs
        # created within/(as child of)
        # mditem be clubbed as cgens
        # and returned
        self.mditem_ctxstack = []

    def __exit__(self, *args):
        super().__exit__(*args)
        html._charref = self._stdlib_charref

    def render_to_plain(self, token) -> str:
        if hasattr(token, 'children'):
            inner = [self.render_to_plain(child) for child in token.children]
            return ''.join(inner)
        return html.escape(token.content)

    def render_strong(self, token: span_token.Strong) -> str:
        template = '<strong>{}</strong>'
        return template.format(self.render_inner(token))

    def render_emphasis(self, token: span_token.Emphasis) -> str:
        template = '<em>{}</em>'
        return template.format(self.render_inner(token))

    def render_inline_code(self, token: span_token.InlineCode) -> str:
        template = '<code>{}</code>'
        inner = html.escape(token.children[0].content)
        return template.format(inner)

    def render_strikethrough(self, token: span_token.Strikethrough) -> str:
        template = '<del>{}</del>'
        return template.format(self.render_inner(token))

    @openCloseCtx
    @renderDictOrHC
    def render_image(self, token: span_token.Image, asdict=False) -> str:
        if asdict:
            return Dict({'img':
                         { 'src': token.src, 'title': token.title, 'alt': self.render_to_plain(token)}                })
        raise ValueError
        template = '<img src="{}" alt="{}"{} />'
        if token.title:
            title = ' title="{}"'.format(html.escape(token.title))
        else:
            title = ''
        return template.format(token.src, self.render_to_plain(token), title)

    @openCloseCtx
    @renderDictOrHC
    def render_link(self, token: span_token.Link, asdict=False) -> str:
        if asdict:
            # as dict we don't parse anything super compilicated 
            vv = [_ for _ in self.render_inner(token) if _ is not None]
            assert len(vv) == 1
            target = self.escape_url(token.target)
            title = html.escape(token.title)
            return Dict({'ahref': {'title' : title, 'target': target, 'desc': vv[0].rawText}})

        raise ValueError
        target = self.escape_url(token.target)
        title = html.escape(token.title)
        inner = self.render_inner(token)
        return oj.A_(f"A_{self.key_cursor}", title=title, href = target, cgens=inner)


    def render_auto_link(self, token: span_token.AutoLink) -> str:
        template = '<a href="{target}">{inner}</a>'
        if token.mailto:
            target = 'mailto:{}'.format(token.target)
        else:
            target = self.escape_url(token.target)
        inner = self.render_inner(token)
        return template.format(target=target, inner=inner)

    def render_escape_sequence(self, token: span_token.EscapeSequence) -> str:
        return self.render_inner(token)


    @renderDictOrHC
    def render_raw_text(self, token: span_token.RawText, **kwargs) -> str:
        asdict = kwargs.pop("asdict", False)
        if asdict:
            return Dict({'rawText': html.escape(token.content)})
        return html.escape(token.content)

    @staticmethod
    def render_html_span(token: span_token.HTMLSpan) -> str:
        return token.content


    @captureViewDirective
    @openCtx #all direct childs will belong to cgens
    def render_heading(self, token: block_token.Heading, asdict = False, content_stub = None) -> str:
        if asdict:
            #don't see any reason to return the whole heading block as dict
            raise ValueError
        self.parsing_in_meta_mode = True 
        inner = [_ for _ in self.render_inner(token) if _ is not None]
        self.parsing_in_meta_mode = False
        try:
            heading_text = inner[0].rawText
        except:
            raise ValueError("Cannot deduce heading text for  heading item..markdown content too fancy for this renderer")
        
        return oj.Subsubsection_(f"heading_{self.key_cursor}", heading_text, content_stub)


    def render_quote(self, token: block_token.Quote) -> str:
        elements = ['<blockquote>']
        self._suppress_ptag_stack.append(False)
        elements.extend([self.render(child) for child in token.children])
        self._suppress_ptag_stack.pop()
        elements.append('</blockquote>')
        return '\n'.join(elements)

    @renderDictOrHC
    def render_paragraph(self, token: block_token.Paragraph, asdict=False) -> str:
        if asdict:
            inner = [self.render(child) for child in token.children]
            return Dict({'para':  inner})

        raise ValueError
        vv = [_ for _ in self.render_inner(token) if _ is not None]
        pref = oj.P_(f"P_{self.key_cursor}", cgens=vv)
        return pref
    def render_block_code(self, token: block_token.BlockCode) -> str:
        template = '<pre><code{attr}>{inner}</code></pre>'
        if token.language:
            attr = ' class="{}"'.format('language-{}'.format(html.escape(token.language)))
        else:
            attr = ''
        inner = html.escape(token.children[0].content)
        return template.format(attr=attr, inner=inner)

    @openCloseCtx
    @renderDictOrHC
    def render_list(self, token: block_token.List, asdict=False) -> str:
        if asdict:
            #don't expect the whole list block to be converent to dict
            # 
            raise ValueError

        # collect all list item stubs
        inner = [self.render(child) for child in token.children]
        return oj.Ol_("ol", cgens=inner)

    @renderDictOrHC
    def render_list_item(self, token: block_token.ListItem, asdict=False) -> str:
        if asdict:
            raise ValueError
            return Dict({})
        if len(token.children) == 0:
            return '<li></li>'
        inner = '\n'.join([self.render(child) for child in token.children])
        inner_template = '\n{}\n'
        if self._suppress_ptag_stack[-1]:
            if token.children[0].__class__.__name__ == 'Paragraph':
                inner_template = inner_template[1:]
            if token.children[-1].__class__.__name__ == 'Paragraph':
                inner_template = inner_template[:-1]
        return '<li>{}</li>'.format(inner_template.format(inner))

    def render_table(self, token: block_token.Table) -> str:
        # This is actually gross and I wonder if there's a better way to do it.
        #
        # The primary difficulty seems to be passing down alignment options to
        # reach individual cells.
        template = '<table>\n{inner}</table>'
        if hasattr(token, 'header'):
            head_template = '<thead>\n{inner}</thead>\n'
            head_inner = self.render_table_row(token.header, is_header=True)
            head_rendered = head_template.format(inner=head_inner)
        else: head_rendered = ''
        body_template = '<tbody>\n{inner}</tbody>\n'
        body_inner = self.render_inner(token)
        body_rendered = body_template.format(inner=body_inner)
        return template.format(inner=head_rendered+body_rendered)

    def render_table_row(self, token: block_token.TableRow, is_header=False) -> str:
        template = '<tr>\n{inner}</tr>\n'
        inner = ''.join([self.render_table_cell(child, is_header)
                         for child in token.children])
        return template.format(inner=inner)

    def render_table_cell(self, token: block_token.TableCell, in_header=False) -> str:
        template = '<{tag}{attr}>{inner}</{tag}>\n'
        tag = 'th' if in_header else 'td'
        if token.align is None:
            align = 'left'
        elif token.align == 0:
            align = 'center'
        elif token.align == 1:
            align = 'right'
        attr = ' align="{}"'.format(align)
        inner = self.render_inner(token)
        return template.format(tag=tag, attr=attr, inner=inner)

    @staticmethod
    def render_thematic_break(token: block_token.ThematicBreak) -> str:
        return '<hr />'

    
    #@staticmethod
    @renderDictOrHC
    def render_line_break(self, token: span_token.LineBreak, asdict = False) -> str:
        if asdict:
            return Dict({'br': True})
        raise ValueError
        return '\n' if token.soft else '<br />\n'

    @staticmethod
    def render_html_block(token: block_token.HTMLBlock) -> str:
        return token.content

    @openCloseCtx
    def render_document(self, token: block_token.Document, content_stub=None) -> str:
        #content_stub shoud  tlc 
        #self.footnotes.update(token.footnotes) #TODO
        assert content_stub == None
        
        inner = [_ for _ in self.render_inner(token) if _ is not None]
        if not self.document_key:
            key = f"document_{self.key_cursor}"
        else:
            key = self.document_key
            
        if inner:
            return oj.StackV_(key, cgens = inner)
        # if there is no content then don't create an htmlcomponent 
        return None

    @staticmethod
    def escape_html(raw: str) -> str:
        """
        This method is deprecated. Use `html.escape` instead.
        """
        return html.escape(raw)

    @staticmethod
    def escape_url(raw: str) -> str:
        """
        Escape urls to prevent code injection craziness. (Hopefully.)
        """
        return html.escape(quote(raw, safe='/#:()*?=%@+,&;'))
