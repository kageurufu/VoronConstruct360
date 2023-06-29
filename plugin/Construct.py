import adsk.core, adsk.fusion, adsk.cam, traceback
import tempfile
import json
import os
import sys, pathlib
import base64

path = str(pathlib.Path(__file__).parent.resolve() / 'lib')
sys.path.insert(0, path)

import jsonrpcserver, requests
from .repodb import RepoDB

_save_file = str(pathlib.Path(__file__).parent.resolve() / '_save.json')
_cache_file = str(pathlib.Path(__file__).parent.resolve() / 'cache.sqlite3')
_repo_options = ['PrintersForAnts/Voron-Construct']
_repo_list = None
_token = None


rpc = jsonrpcserver.Service()
rdb = RepoDB(sqlite_file=_cache_file)


def _save_state():
    with open(_save_file, 'w') as f:
        f.write(json.dumps(dict(token=_token, repo_list=_repo_list, repo_options=_repo_options)))                 


def _load_state():
    global _token, _repo_list, _repo_options
    try:
        with open(_save_file, 'r') as f:
            state = json.load(f)
            _token = state['token']
            _repo_list = state['repo_list']
            _repo_options = state['repo_options']
    except (OSError, KeyError, ValueError):
        pass    
        

def _download(apiUrl, extension=''):
    if extension:
        extension = '.{}'.format(extension)
    
    # Create a temporary file with the file extension
    response = requests.get(apiUrl, headers={'Accept': 'application/vnd.github.raw', 'Authorization': 'Bearer {}'.format(_token)})    
    temp_file = tempfile.NamedTemporaryFile(delete=False, suffix=extension)
    temp_file.write(response.content)
    return temp_file.name
    

@rpc.method
def get_screenshot():
    with tempfile.TemporaryDirectory() as tmp_dir:
        fname = os.path.join(tmp_dir, 'thumbnail.png')
        _app.activeViewport.saveAsImageFile(fname, 256, 256)
        with open(fname, 'rb') as f:
            return 'data:image/png;base64,{}'.format(base64.b64encode(f.read()).decode('utf8'))

@rpc.method
def upload_thumbnail(repo, path, data):
    try:        
        if data.startswith('data:image/png;base64,'):
            data = data[22:]
        rdb.upload_thumbnail(repo, path, data)  
    except Exception as e:
        raise jsonrpcserver.RpcException(code=-200, message=str(e))


@rpc.method
def get_state():
    repo_list = [dict(**r) for r in _repo_list]
    for r in repo_list:
        r['children'] = _get_repo_tree(r['id'])
    return dict(token=_token, repo_list=repo_list)
    

@rpc.method
def get_repo_options():
    return _repo_options


@rpc.method
def set_repo_options(repos):
    global _repo_options
    _repo_options = repos
    _save_state()


@rpc.method
def set_repo_list(repos):
    global _repo_list
    _repo_list = repos
    _save_state()


@rpc.method
def get_thumb(url):
    return rdb.get_thumb(url)


def _get_repo_tree(repo=None):
    rdb.github_token = _token
    contents = None
    try:
        for r in repo.split(','):
            owner, repo_name, *repo_path = r.split('/')
            if contents is None:
                contents = rdb.get_repository_contents('{}/{}'.format(owner, repo_name), path=repo_path, id_prefix=repo)
            else:
                contents = rdb.merge_contents(contents, rdb.get_repository_contents('{}/{}'.format(owner, repo_name), path=repo_path))
    except Exception as e:
        raise jsonrpcserver.RpcException(code=-100, message=str(e))
    return contents


@rpc.method
def get_repo_tree(repo=None, token=None):
    global _token, _repo_options
    _token = token
    contents = _get_repo_tree(repo=repo)
    _repo_options = [r for r in _repo_options if r != repo]
    _repo_options.insert(0, repo)
    _save_state()
    return contents


@rpc.method
def open_model(url, content_type):
    fileName = _download(url, extension=content_type)
    app = adsk.core.Application.get()        
    
    importManager = app.importManager
    try:
        options = create_import_options(fileName, content_type)
    except:
        raise ValueError("Failed to create options for {} | {}".format(fileName, content_type))
    
    try:
        importManager.importToNewDocument(options)
    except:
         if _ui:
            _ui.messageBox('Failed:\n{}'.format(traceback.format_exc()))
  

@rpc.method
def import_model(url, content_type):
    fileName = _download(url, extension=content_type)
    app = adsk.core.Application.get()        
    importManager = app.importManager

    # Get active design
    product = app.activeProduct
    design = adsk.fusion.Design.cast(product)
    
    options = create_import_options(fileName, content_type)
    
    target = design.activeComponent
    if isinstance(options, (adsk.core.DXF2DImportOptions, adsk.core.SVGImportOptions)):
        target = design.activeEditObject
    try:
        importManager.importToTarget(options, target);
    except:
         if _ui:
            _ui.messageBox('Failed:\n{}'.format(traceback.format_exc()))
  

def create_import_options(filename, ext):
    if ext in ('stp', 'step'):
        return adsk.core.Application.get().importManager.createSTEPImportOptions(filename)
    elif ext == 'f3d':
        return adsk.core.Application.get().importManager.createFusionArchiveImportOptions(filename)
    elif ext == 'svg':
        return adsk.core.Application.get().importManager.createSVGImportOptions(filename)
    elif ext == 'dxf':
        return adsk.core.Application.get().importManager.createDXF2DImportOptions(filename)

# global set of event handlers to keep them referenced for the duration of the command
handlers = []
_app = adsk.core.Application.cast(None)
_ui = adsk.core.UserInterface.cast(None)
num = 0


# Event handler for the commandExecuted event.
class ShowPaletteCommandExecuteHandler(adsk.core.CommandEventHandler):
    def __init__(self):
        super().__init__()
    def notify(self, args):
        try:
            # Create and display the palette.
            palette = _ui.palettes.itemById('voronConstruct')
            if not palette:
                palette = _ui.palettes.add('voronConstruct', 'Voron Construct, CAD...Lots of CAD', 'palette.html', True, True, True, 700, 200, True)

                # Dock the palette to the right side of Fusion window.
                palette.dockingState = adsk.core.PaletteDockingStates.PaletteDockStateRight
    
                # Add handler to HTMLEvent of the palette.
                onHTMLEvent = MyHTMLEventHandler()
                palette.incomingFromHTML.add(onHTMLEvent)   
                handlers.append(onHTMLEvent)
    
                # Add handler to CloseEvent of the palette.
            else:
                palette.isVisible = True                               
        except:
            _ui.messageBox('Command executed failed: {}'.format(traceback.format_exc()))


# Event handler for the commandCreated event.
class ShowPaletteCommandCreatedHandler(adsk.core.CommandCreatedEventHandler):
    def __init__(self):
        super().__init__()              
    def notify(self, args):
        try:
            command = args.command
            onExecute = ShowPaletteCommandExecuteHandler()
            command.execute.add(onExecute)
            handlers.append(onExecute)    
                                             
        except:
            _ui.messageBox('Failed:\n{}'.format(traceback.format_exc()))     



# Event handler for the commandExecuted event.
class SendInfoCommandExecuteHandler(adsk.core.CommandEventHandler):
    def __init__(self):
        super().__init__()
    def notify(self, args):
        try:
            # Send information to the palette. This will trigger an event in the javascript
            # within the html so that it can be handled.
            palette = _ui.palettes.itemById('voronConstruct')
            if palette:
                global num
                num += 1
                palette.sendInfoToHTML('send', 'This is a message sent to the palette from Fusion. It has been sent {} times.'.format(num))                        
        except:
            _ui.messageBox('Command executed failed: {}'.format(traceback.format_exc()))


# Event handler for the palette HTML event.                
class MyHTMLEventHandler(adsk.core.HTMLEventHandler):
    def __init__(self):
        super().__init__()
    def notify(self, args):
        try:
            htmlArgs = adsk.core.HTMLEventArgs.cast(args)            
            if htmlArgs.action == 'jsonrpc':
                response = rpc.handle_request_body(htmlArgs.data);
                if response is not None:
                    palette = _ui.palettes.itemById('voronConstruct')
                    palette.sendInfoToHTML('jsonrpc', response);
        except:
            _ui.messageBox('Failed:\n{}'.format(traceback.format_exc()))   


def run(context):        
    try:
        global _ui, _app
        _app = adsk.core.Application.get()
        _ui  = _app.userInterface
        
        # Add a command that displays the panel.
        showPaletteCmdDef = _ui.commandDefinitions.itemById('openVoronConstruct')
        if not showPaletteCmdDef:
            showPaletteCmdDef = _ui.commandDefinitions.addButtonDefinition('openVoronConstruct', 'Voron Construct', 'I Need CAD...Lots of CAD', 'Resources/openVoronConstruct')

            # Connect to Command Created event.
            onCommandCreated = ShowPaletteCommandCreatedHandler()
            showPaletteCmdDef.commandCreated.add(onCommandCreated)
            handlers.append(onCommandCreated)
        
         
        # Add the command to the toolbar.
        panel = _ui.workspaces.itemById('FusionSolidEnvironment').toolbarPanels.itemById('InsertPanel')

        cntrl = panel.controls.itemById('openVoronConstruct')
        if not cntrl:
            cntrl = panel.controls.addCommand(showPaletteCmdDef, )
            cntrl.isPromoted = True

        _load_state()

    except:
        if _ui:
            _ui.messageBox('Failed:\n{}'.format(traceback.format_exc()))


def stop(context):
    try:        
        # Delete the palette created by this add-in.
        palette = _ui.palettes.itemById('voronConstruct')
        if palette:
            palette.deleteMe()
            
        cmd = _ui.commandDefinitions.itemById('openVoronConstruct')
        if cmd:
            cmd.deleteMe()
        
        # Delete controls and associated command definitions created by this add-ins
        panel = _ui.workspaces.itemById('FusionSolidEnvironment').toolbarPanels.itemById('InsertPanel')
        if panel:
            cmd = panel.controls.itemById('openVoronConstruct')
            if cmd:
                cmd.deleteMe()
    except:
        if _ui:
            _ui.messageBox('Failed:\n{}'.format(traceback.format_exc()))