import vtk
from markers import Marker

import pickle
import socket

from scipy import array, zeros

debug=False

class Viewer:
    def update_viewer(self, event, *args):
        raise NotImplementedError


class UndoRegistry:
    __sharedState = {}
    commands = []
    lastPop = None, []

    def __init__(self):
        self.__dict__ = self.__sharedState    

    def push_command(self, func, *args):
        self.commands.append((func, args))

    def undo(self):
        if len(self.commands)==0: return
        func, args = self.commands.pop()
        self.lastPop = func, args
        func(*args)

        
    def flush(self):
        self.commands = []

    def get_last_pop(self):
        return self.lastPop

class EventHandler:
    __sharedState = {}
    markers = vtk.vtkActorCollection()
    defaultColor = (0,0,1)
    labelsOn = 1
    observers = {}
    selected = {}
    __NiftiQForm=None
    __NiftiSpacings=(1.0,1.0,1.0)

    def __init__(self):
        self.__dict__ = self.__sharedState            

    def add_selection(self, marker):
        self.selected[marker] = 1
        self.notify('select marker', marker)
        
    def remove_selection(self, marker):
        if self.selected.has_key(marker):
            del self.selected[marker]
            self.notify('unselect marker', marker)
        
        
    def select_new(self, marker):
        for oldMarker in self.selected.keys():
            self.remove_selection(oldMarker)
        self.add_selection(marker)
    
    def add_marker(self, marker):
        # break undo cycle 
        func, args = UndoRegistry().get_last_pop()
        #print 'add', func, args
        if len(args)==0 or \
               (func, args[0]) != (self.add_marker, marker):
            UndoRegistry().push_command(self.remove_marker, marker)
        self.markers.AddItem(marker)
        self.notify('add marker', marker)


    def remove_marker(self, marker):
        # break undo cycle

        func, args = UndoRegistry().get_last_pop()
        #print 'remove', func, args
        if len(args)==0 or \
               (func, args[0]) != (self.remove_marker, marker):
            UndoRegistry().push_command(self.add_marker, marker)
        self.markers.RemoveItem(marker)
        self.notify('remove marker', marker)

    def get_markers(self):
        return self.markers

    def get_markers_as_seq(self):
        numMarkers = self.markers.GetNumberOfItems()
        self.markers.InitTraversal()
        return [self.markers.GetNextActor() for i in range(numMarkers)]


    def set_default_color(self, color):
        self.defaultColor = color

    def get_default_color(self):
        return self.defaultColor


    def save_markers_as(self, fname):
        self.markers.InitTraversal()
        numMarkers = self.markers.GetNumberOfItems()
        lines = []; conv_lines = []
        
        #self.printTalairachResults()

        for i in range(numMarkers):
            marker = self.markers.GetNextActor()
            if marker is None: continue
            else:
                #XXX if self.__Nifti:
                if self.__NiftiQForm is not None:
                    conv_marker=marker.convert_coordinates(self.__NiftiQForm,self.__NiftiSpacings)
                    #XXX conv_marker=marker.convert_coordinates(QForm)
                    center = conv_marker.get_center()
                    request = "1,%i,%i,%i" % (int(center[0]),int(center[1]),int(center[2]))
                    result=self.query_talairach(request)
                    conv_lines.append("%.3f, %.3f, %.3f, %s"%(center[0],center[1],center[2],result))

                lines.append(marker.to_string())
        lines.sort()

        fh = file(fname, 'w')
        fh.write('\n'.join(lines) + '\n')
        if self.__NiftiQForm is not None:
            fn = file(fname+".conv", 'w') #only needed for nifti, but what the hell
            conv_lines.sort()
            fn.write('\n'.join(conv_lines) + '\n')
    
    def query_talairach(self, request):
            sock = socket.socket()
            sock.connect(("talairach.org",1600))
            sock.settimeout(10.0)
            sock.send(request)
            res = sock.recv(1000)
            #print "res=", res
            return res
    
    def printTalairachResults(self):
        """For testing: query talairach-daemon and print results"""
        self.markers.InitTraversal()
        numMarkers = self.markers.GetNumberOfItems()
        
        for i in range(numMarkers):
            marker = self.markers.GetNextActor()
            if marker is None: continue
            
            if self.__NiftiQForm is not None:
                conv_marker=marker.convert_coordinates(self.__NiftiQForm,self.__NiftiSpacings)
                center = conv_marker.get_center()
                request = "1,%i,%i,%i" % (int(center[0]),int(center[1]),int(center[2]))
            if debug:
                print "Marker", center, ":", self.query_talairach(request)
                
        
    def setNifti(self,QForm,spacings):
        self.__NiftiQForm=QForm
        self.__NiftiSpacings=spacings

    def set_vtkactor(self, vtkactor):
        if debug:
            print "EventHandler.set_vtkactor()"
        self.vtkactor = vtkactor

    def save_registration_as(self, fname):
        if debug:
            print "EventHandler.save_registration_as(", fname,")"
        fh = file(fname, 'w')

        # XXX mcc: somehow get the transform for the VTK actor. aiieeee
        #xform = self.vtkactor.GetUserTransform()
        loc = self.vtkactor.GetOrigin()
        pos = self.vtkactor.GetPosition()
        scale = self.vtkactor.GetScale()
        mat = self.vtkactor.GetMatrix()
        orient = self.vtkactor.GetOrientation()
        
        if debug:
            print "EventHandler.save_registration_as(): vtkactor has origin, pos, scale, mat, orient=", loc, pos, scale, mat, orient, "!!"


        def vtkmatrix4x4_to_array(vtkmat):
            scipy_array = zeros((4,4), 'd')

            for i in range(0,4):
                for j in range(0,4):
                    scipy_array[i][j] = mat.GetElement(i,j)

            return scipy_array

        scipy_mat = vtkmatrix4x4_to_array(mat)

        pickle.dump(scipy_mat, fh)
        fh.close()
        
        
    def load_markers_from(self, fname):

        self.notify('render off')
        for line in file(fname, 'r'):
            marker = Marker.from_string(line)
            self.add_marker(marker)
        self.notify('render on')
        UndoRegistry().flush()

    def attach(self, observer):
        self.observers[observer] = 1

    def detach(self, observer):
        try:
            del self.observers[observer]
        except KeyError: pass

    def notify(self, event, *args):
        for observer in self.observers.keys():
            if debug:
                print "EventHandler.notify(", event, "): calling update_viewer for ", observer
            observer.update_viewer(event, *args)

    def get_labels_on(self):
        return self.labelsOn

    def set_labels_on(self):
        self.labelsOn = 1
        self.notify('labels on')

    def set_labels_off(self):
        self.labelsOn = 0
        self.notify('labels off')


    def is_selected(self, marker):
        return self.selected.has_key(marker)

    def get_selected(self):
        return self.selected.keys()

    def get_num_selected(self):
        return len(self.selected)
