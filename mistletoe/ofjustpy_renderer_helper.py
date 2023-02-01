import functools
from addict import Dict
import ofjustpy as oj

from typing import Any, NamedTuple

# def chainme(func):
#     @functools.wraps(func)
#     def wrapper(*args, **kwargs):
#         renderer_obj = args[0]
#         token = args[1]
#         res = func(*args, **kwargs)
#         return res

#     return wrapper



def captureViewDirective(func):
    """
    L6 headings are view directives; should be removed from rendering 
    """
    @functools.wraps(func)
    def wrapper(*args, **kwargs):
        renderer_obj = args[0]
        token = args[1]
        if token.level == 6:
            renderer_obj.parsing_in_meta_mode = True
            inner = [_ for _ in renderer_obj.render_inner(token) if _ is not None]
            renderer_obj.parsing_in_meta_mode = False
            view_directive = inner[0].rawText
            handler_type, handler_funcname = view_directive.split(":")
            if handler_funcname != 'None':
                renderer_obj.mditem_view_handlers[handler_type] = renderer_obj.mdview_funclookup[handler_funcname]
            else:
                renderer_obj.mditem_view_handlers[handler_type] = None

            print ("adding view directive = ", handler_type, " ",  handler_funcname) 

            return
        else:
            return func(*args, **kwargs)

    return wrapper

# all about context of mditems
ctx_depth = 0

class ctx(NamedTuple):
    ctxtype: Any
    ctxhandle: Any

def pop_covering_ctx(covering_ctx_stack, ctxtype):
    global ctx_depth
    last_ctx = covering_ctx_stack.pop()
    spaces = "".join([" " for i in range(ctx_depth)])
    print (f"{spaces} </{last_ctx.ctxtype}>")
    ctx_depth -= 1
    while True:
        if not covering_ctx_stack:
            break
        if last_ctx.ctxtype == ctxtype:
            break
        last_ctx = covering_ctx_stack.pop()
        spaces = "".join([" " for i in range(ctx_depth)])
        print (f"{spaces} </{last_ctx.ctxtype}>")
        ctx_depth -= 1

        
def append_covering_ctx(covering_ctx_stack, ctxtype,  ctxhandle):
    """
    context_handle == None implies a closed context 
    """
    global ctx_depth
    needs_pop  = False
    # check if ctx appears earlier
    for ctxitem in covering_ctx_stack:
        if ctxitem.ctxtype == ctxtype:
            needs_pop = True

    if needs_pop:
        pop_covering_ctx(covering_ctx_stack, ctxtype)
    spaces = "".join([" " for i in range(ctx_depth)])
    print(f"{spaces} <", ctxtype, ">")
    covering_ctx_stack.append(ctx(ctxtype,  ctxhandle))
    ctx_depth += 1

        
def attach_to_covering_ctx(covering_ctx_stack, ref):
    top_ctx = covering_ctx_stack[-1]
    if top_ctx.ctxhandle is None:
        return ref
    else:
        print (f"{ref.key} is-attached-to {top_ctx.ctxhandle.key}")
        top_ctx.ctxhandle.cgens.append(ref)
        return None
    
def openCtx(func):
    @functools.wraps(func)
    def wrapper(*args, **kwargs):
        renderer_obj = args[0]
        token = args[1]

        mditem_ctxstack = renderer_obj.mditem_ctxstack
        mditem_name = func.__name__.replace("render_", "")
        if mditem_name == "heading":
            mditem_name += str(token.level)
        
        key_cursor = 0
        head_ref = oj.StackV_(f"{mditem_name}_{key_cursor}", cgens = [])
        append_covering_ctx(mditem_ctxstack,  mditem_name,  head_ref)
        res = func(*args, content_stub=head_ref,  **kwargs)
        return res

    return wrapper


def openCloseCtx(func):
    @functools.wraps(func)
    def wrapper(*args, **kwargs):
        renderer_obj = args[0]
        token = args[1]

        mditem_ctxstack = renderer_obj.mditem_ctxstack
        mditem_name = func.__name__.replace("render_", "")
        if mditem_name == "heading":
            mditem_name += str(token.level)
        
        key_cursor = 0
        append_covering_ctx(mditem_ctxstack,  mditem_name,  None)
        res = func(*args,  **kwargs)
        pop_covering_ctx(mditem_ctxstack, mditem_name)
        return res

    return wrapper



def renderDictOrHC(func):
    """
    takes a misltetoe orig render function but changes
    rendering to dict or oj
    """
    @functools.wraps(func)
    def wrapper(*args, **kwargs):
        renderer_obj = args[0]
        token = args[1]
        mditem_ctxstack = renderer_obj.mditem_ctxstack
        mditem_name = func.__name__.replace("render_", "")
        view_func_name = mditem_name + "_view_handler"
        collect_as_dict = True
        
        # if the child has its own viewer function then deploy
        # that instead of collecting the text
        
        if view_func_name in renderer_obj.mditem_view_handlers:
            if renderer_obj.mditem_view_handlers[view_func_name]:
                collect_as_dict = False
        
        if renderer_obj.parsing_in_meta_mode and collect_as_dict:
            #don't create htmlcomponent
            #simply return all attributes as Dict object
            res = func(*args, asdict=True)
            return res
        else:
            
            if view_func_name in renderer_obj.mditem_view_handlers:
                if renderer_obj.mditem_view_handlers[view_func_name]:
                    # build a dict of the subtree dom
                    # and pass the dict to the viewer function
                    renderer_obj.parsing_in_meta_mode = True
                    content_dict = [renderer_obj.render(child) for child in  token.children]
                    res = Dict({mditem_name: content_dict})
                    renderer_obj.parsing_in_meta_mode = False
                    mditem_view_stub = renderer_obj.mditem_view_handlers[view_func_name](res, renderer_obj.key_cursor)
                    renderer_obj.key_cursor += 1
                    return attach_to_covering_ctx(mditem_ctxstack,  mditem_view_stub)


            #create html component stub
            hcstub = func(*args, **kwargs)
            hcstub = attach_to_covering_ctx(mditem_ctxstack, hcstub)
            return hcstub
        #return inner

    return wrapper
