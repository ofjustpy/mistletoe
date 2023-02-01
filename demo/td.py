# this is to drive the final/more polished version of ofjustpy renderer
import ofjustpy as oj
import justpy as jp
import mistletoe
# import ofjustpy  as oj
# from addict import Dict
# import justpy as jp
import md_view_handlers
from starlette.testclient import TestClient

def launcher(request):
    session_id = "abc"
    session_manager = oj.get_session_manager(session_id)
    md_view_handlers.session_manager = session_manager
    print ("session_manager = ", session_manager)
    with oj.sessionctx(session_manager):
        md_view_handlers.session_manager = session_manager

        with open('for_td_new.md', 'r') as fin:
            with session_manager.uictx("mdelems") as _ictx:
                rendered = mistletoe.markdown(fin,
                                              mistletoe.OfjustpyRenderer,
                                              md_view_handlers=md_view_handlers,
                                              session_manager = session_manager)

                oj.Container_("tlc", cgens=[rendered])
                wp_ = oj.WebPage_("basicpage", cgens = [_ictx.tlc], title="test misltetoe")
                wp = wp_()
                wp.session_manager = session_manager
    return wp
jp.CastAsEndpoint(launcher, "/", "basicPage")
app = jp.app            
 
            
#client = TestClient(app)
#response = client.get('/')
