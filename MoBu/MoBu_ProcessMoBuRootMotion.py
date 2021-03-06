from pyfbsdk import *
from pyfbsdk_additions import *
import os

# Application references
app = FBApplication()
system = FBSystem()
scene = system.Scene

# Globals
version = 1.0
branchCache = []
append = '_RootMotion.fbx'
errors = 0
invertZ = FBButton()
hipZisY = FBButton()
deleteUnwanted = FBButton()
unwantedJoints = [ 
        "CC_Base_R_UpperarmTwist02", 
        "CC_Base_L_UpperarmTwist02", 
        "CC_Base_R_RibsTwist", 
        "CC_Base_R_Breast", 
        "CC_Base_L_RibsTwist", 
        "CC_Base_L_Breast", 
        "CC_Base_L_Ribs", 
        "CC_Base_R_Ribs", 
        "CC_Base_Tongue01", 
        "CC_Base_Tongue02", 
        "CC_Base_Tongue03", 
        "CC_Base_Teeth02", 
        "CC_Base_UpperJaw", 
        "CC_Base_Teeth01", 
        "CC_Base_L_ThighTwist02", 
        "CC_Base_L_CalfTwist02", 
        "CC_Base_R_ThighTwist02", 
        "CC_Base_R_CalfTwist02", 
        "CC_Base_Pelvis"
    ]


# Get Translation offset for pelvis/hips node, in relation to the root/reference
def getHipsOffset(char):
    m = FBMatrix()
    char.GetTransformOffset(FBBodyNodeId.kFBHipsNodeId, m)
    x = m[12]
    y = m[13]
    z = m[14]
    
    return FBVector3d(x,y,z)
    

# Copy animation curves from source to destination (pelvis to root)
def copyAnimation(src, dst):   
    
    # Set playback to 24fps
    FBPlayerControl().SetTransportFps(FBTimeMode.kFBTimeMode24Frames)
    #FBPlayerControl().SetTransportFps(FBTimeMode.kFBTimeMode30Frames)
    FBPlayerControl().SnapMode = FBTransportSnapMode.kFBTransportSnapModeSnapAndPlayOnFrames
    
    # Plot options
    options = FBPlotOptions()
    options.PlotAllTakes = False
    options.PlotOnFrame = True
    options.PlotPeriod = FBTime(0,0,0,1)
    options.UseConstantKeyReducer = False
    options.PlotTranslationOnRootOnly = False
    
    # Key dst/root rotations
    dstRef = dst.Clone()
    dstRef.Name = 'Cache'
    null = src.Clone()
    null.Name = 'Dummy'
    null.Show = True
    mgr = FBConstraintManager()
    con = mgr.TypeCreateConstraint(3) #parent/child
    con.ReferenceAdd(0, null)
    con.ReferenceAdd(1, src)
    con.Weight = 100
    con.Active = True
    
    null.Selected = True
    dstRef.Selected = True
    #system.CurrentTake.PlotTakeOnSelected(FBTime(0,0,0,1))
    system.CurrentTake.PlotTakeOnSelected(options)
    con.Active = False
    null.Selected = False
    dstRef.Selected = False
    
    # Copy translation keys to destination
    dst.Translation.GetAnimationNode().Nodes[0].FCurve = null.Translation.GetAnimationNode().Nodes[0].FCurve
    dst.Translation.GetAnimationNode().Nodes[1].FCurve = null.Translation.GetAnimationNode().Nodes[1].FCurve
    dst.Translation.GetAnimationNode().Nodes[2].FCurve = null.Translation.GetAnimationNode().Nodes[2].FCurve
    
    # Delete source keys
    #src.Translation.GetAnimationNode().Nodes[0].FCurve = FBFCurve() #X Trans (lcl)
    #src.Translation.GetAnimationNode().Nodes[1].FCurve = FBFCurve() #Y Trans (lcl)
    
    # Give dst back it's orignal rotation keys (now plotted, in case it didn't have any or they were sparse)
    dst.Rotation.GetAnimationNode().Nodes[0].FCurve = dstRef.Rotation.GetAnimationNode().Nodes[0].FCurve
    dst.Rotation.GetAnimationNode().Nodes[1].FCurve = dstRef.Rotation.GetAnimationNode().Nodes[1].FCurve
    dst.Rotation.GetAnimationNode().Nodes[2].FCurve = dstRef.Rotation.GetAnimationNode().Nodes[2].FCurve
    
    null.FBDelete()
    dstRef.FBDelete()
    con.FBDelete()


# Invert Z Translation (neg to abs)
def invertZTranslation(dst):
    
    # Expect negative value keys, force absolute values
    for key in dst.Translation.GetAnimationNode().Nodes[2].FCurve.Keys:
        key.Value = abs(key.Value)
    

# Find skeleton root. Traverse scene, look for an FBModelSkeleton node named *root*
def getSkeletonRoot():
    root = None
    for comp in scene.Components:
        if 'root' == comp.Name.lower() and (comp.__class__ is FBModelSkeleton or comp.__class__ is FBModelRoot):
            root = comp
            break
    
    return root


# Get skeleton pelvis, traversing down from a given root node
def getSkeletonPelvis(root):
    pelvis = None
    for child in root.Children:
        if 'pelvis' == child.Name.lower():
            pelvis = child
            break
    
    return pelvis
    

# Get the character reference based on a given FBModelSkeleton node
def getCharacterFromRoot(root):
    char = None
    for src in range(root.GetSrcCount()):
        src_obj = root.GetSrc(src)
        if src_obj.__class__ is FBCharacter:
            char = src_obj
            break
    
    return char


# Move root animation down n units, and counter-move pelvis up by the same amount
def offsetHipsAndRoot(root, pelvis, offset):
    
    # Root translation
    for key in root.Translation.GetAnimationNode().Nodes[1].FCurve.Keys:
        key.Value -= offset[1]
    
    # Pelvis translation
    for i in range(3):
        for key in pelvis.Translation.GetAnimationNode().Nodes[i].FCurve.Keys:
            # X
            if i == 0:
                key.Value = 0 # Delete - has been transferred to root
            
            # Y
            elif i == 1:
                
                # Delete if Z-up, otherwise plot offset
                if hipZisY.State:
                    key.Value = 0
                else:
                    key.Value = offset[1]
            
            # Z
            else:
                
                # Plot offset if Z-up, otherwise delete
                if hipZisY.State:
                    key.Value = offset[1]
                else:
                    key.Value = 0


# Get hierarchy branch
def getBranch(topModel):
    global branchCache
    branchCache = []
    _getBranch(topModel)
    return branchCache
def _getBranch(topModel):
    global branchCache
    for childModel in topModel.Children:
        _getBranch(childModel)

    branchCache.append(topModel)
    

# Insert stance pose at frame -1
def insertStancePose(char, root):
    
    stanceFrame = FBPlayerControl().LoopStart.GetFrame() - 1
    
    children = getBranch(root)
    char.InputType = FBCharacterInputType.kFBCharacterInputStance
    char.ActiveInput = True
    
    scene.Evaluate()
    
    for child in children:
        if child.__class__ is FBModelSkeleton and child.Translation.GetAnimationNode() and child.Rotation.GetAnimationNode():
            #print "setting key for {}".format(child.Name)
            child.Translation.GetAnimationNode().KeyAdd(FBTime(0,0,0,stanceFrame), [child.Translation[0], child.Translation[1], child.Translation[2]])
            child.Rotation.GetAnimationNode().KeyAdd(FBTime(0,0,0,stanceFrame), [child.Rotation[0], child.Rotation[1], child.Rotation[2]])
    
    root.Translation.GetAnimationNode().KeyAdd(FBTime(0,0,0,stanceFrame), [0, 0, 0])
    root.Rotation.GetAnimationNode().KeyAdd(FBTime(0,0,0,stanceFrame), [0, 0, 0])
    
    char.ActiveInput = False
    FBPlayerControl().LoopStart = FBTime(0,0,0,stanceFrame)


# Main process
def processTrack():
    global errors
    
    # Grab scene references
    root = getSkeletonRoot()
    if not root:
        errors += 1
        return False
    
    pelvis = getSkeletonPelvis(root)
    char = getCharacterFromRoot(root)
    offset = None
    
    # Find hips offset
    if not pelvis or not char:
        errors += 1
        return False

    offset = getHipsOffset(char)
    
    # Process file
    copyAnimation(pelvis, root)
    if invertZ.State:
        invertZTranslation(root)

    offsetHipsAndRoot(root, pelvis, offset)
    insertStancePose(char, root)

    # Delete unwanted bones, if requested
    if deleteUnwanted.State:
        toDelete = []
        for comp in scene.Components:
            if comp.Name in unwantedJoints:
                toDelete.append(comp)
        
        if len(toDelete) > 0:
            for i in range(len(toDelete), 0, -1):
                x = i-1
                toDelete[x].FBDelete()
    
    return True
        

# Save file with an appended filename
def saveAs():
     filename = app.FBXFileName.replace('.fbx', append) 
     app.FileSave(filename)
    

# List all FBX files in a directory and process them
def processFiles():
    global errors
    openDir = FBFolderPopup()
    openDir.Caption = "Select motion file folder"
    openDir.Path = os.path.dirname(app.FBXFileName)
    
    if openDir.Execute():
        
        # Loop through all files in folder
        errors = 0
        fileCount = 0
        for file in os.listdir(openDir.Path):
            if file.endswith('.fbx') and append not in file:
                fullPath = os.path.join(openDir.Path, file)

                app.FileOpen(fullPath) # Open file
                status = processTrack() # Process
                if status:
                    saveAs() # Save
                    fileCount += 1
        
        app.FileNew()
        grammar = 'file' if fileCount == 1 else 'files'
        grammar2 = 'error' if errors == 1 else 'errors'
        FBMessageBox("Done!", "All finished -- Processed {} {}, {} {}".format(fileCount, grammar, errors, grammar2), "OK" )


##
## GUI BUTTON WRAPPERS
##

def buttonLoad(control, event):
    processFiles()


##
## POPULATE LAYOUT AND UI ELEMENTS
##

def PopulateLayout(mainLyt):
    global hipZisY, invertZ, deleteUnwanted

    # Vertical box layout
    main = FBVBoxLayout()
    x = FBAddRegionParam(5,FBAttachType.kFBAttachLeft,"")
    y = FBAddRegionParam(5,FBAttachType.kFBAttachTop,"")
    w = FBAddRegionParam(-5,FBAttachType.kFBAttachRight,"")
    h = FBAddRegionParam(-5,FBAttachType.kFBAttachBottom,"")
    
    mainLyt.AddRegion("main", "main",x,y,w,h)
    mainLyt.SetControl("main", main)
    
    l = FBLabel()
    l.Caption = "This script prompts you for a path to your animation exports, then proceeds to process all matching fbx files in that directory. \n\nEach file MUST have been saved as a selection, in order to retain the character definition (used to find hips offset).\n\nDO NOT USE THIS SCRIPT FOR PARENTED CHARACTERS (AKA DRIVING CARS, ETC)"
    l.WordWrap = True
    l.Justify = FBTextJustify.kFBTextJustifyLeft
    main.Add(l, 130)
 
    box = FBHBoxLayout(FBAttachType.kFBAttachRight)
    b = FBButton()
    b.Caption = "Browse and process files"
    b.Justify = FBTextJustify.kFBTextJustifyCenter
    box.AddRelative(b, 1.0)
    b.OnClick.Add(buttonLoad)
    main.Add(box, 35)
    
    box = FBHBoxLayout(FBAttachType.kFBAttachRight)
    deleteUnwanted.Caption = "Delete unwanted animation bones (Nubs, etc)?"
    deleteUnwanted.Style = FBButtonStyle.kFBCheckbox 
    deleteUnwanted.Justify = FBTextJustify.kFBTextJustifyLeft
    deleteUnwanted.State = True
    box.AddRelative(deleteUnwanted, 1.0)
    main.Add(box, 20)

    box = FBHBoxLayout(FBAttachType.kFBAttachRight)
    invertZ.Caption = "Invert Z axis? (for Z-up motion file)"
    invertZ.Style = FBButtonStyle.kFBCheckbox 
    invertZ.Justify = FBTextJustify.kFBTextJustifyLeft
    invertZ.State = False
    box.AddRelative(invertZ, 1.0)
    main.Add(box, 20)
    
    box = FBHBoxLayout(FBAttachType.kFBAttachRight)
    hipZisY.Caption = "Treat Hips TZ as TY? (for Z-up character)"
    hipZisY.Style = FBButtonStyle.kFBCheckbox 
    hipZisY.Justify = FBTextJustify.kFBTextJustifyLeft
    hipZisY.State = False
    box.AddRelative(hipZisY, 1.0)
    main.Add(box, 15)


##
## CREATE THE TOOL REGISTRATION IN MOBU. THIS IS ALSO WHERE WE CAN
## STORE 'GLOBAL' VARIABLES, FOR LACK OF BETTER SCOPING WITHOUT USING A CLASS
##

def CreateTool():
    global t
    
    # Tool creation will serve as the hub for all other controls
    name = "iKinema exporter v{0:.2f}".format(version)
    t = FBCreateUniqueTool(name)
    t.StartSizeX = 330
    t.StartSizeY = 320
    PopulateLayout(t)
    ShowTool(t)


CreateTool()
#processTrack()
