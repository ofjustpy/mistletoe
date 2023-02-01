import ofjustpy as oj
#this is the default list item viwer
from tailwind_tags import *
from jsonpath_ng import jsonpath, parse

session_manager = None

def list_item(cgens, key_cursor):
    return oj.StackV_("blahblah", cgens=[])

def gridify(mditem_data, key_cursor):
    print ("in gridify ", mditem_data)
    return oj.StackG_("mygrid", num_cols=3, cgens=mditem_data['list'])


#this is the default list item viwer
def para_as_span_viewer(mditem_data, key_cursor):
    """
    strip para and graph the rawText to define the span
    """

    print (mditem_data)
    jsonpath_expr = parse('$.list_item[0].para[0].rawText')
    span_text = [_.value for _ in jsonpath_expr.find(mditem_data)][0]
    print ('span_text = ', span_text)
    return oj.Span_("aspan", text =span_text)

#this is the default list item viwer
def href_image_viewer(mditem_data, key_cursor):
    #print ("in href_image_viewer  = ", mditem_data)
    #/list_item/0/para/rawText
    jsonpath_expr = parse('$.list_item[0].para[0].ahref')
    _d  = [_.value for _ in jsonpath_expr.find(mditem_data)][0]
    jsonpath_expr = parse('$.list_item[0].para[2].img')
    _i = [_.value for _ in jsonpath_expr.find(mditem_data)][0]
    print (_i)
    with session_manager.uictx(f"item_{key_cursor}") as _ictx:
        href = oj.A_("ahref", text= _d.desc, title = _d.title, href=_d.target)
        img = oj.Img_("img", src =_i.src, title = _d.title, alt=_d.desc, pcp=["object-contain"])
        return oj.StackV_("box", cgens=[href, img])


    
