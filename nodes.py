# coding: utf-8

from PyQt4.QtGui import *
from PyQt4.QtCore import *

rad = 5

class Node(QGraphicsRectItem):
    """docstring for Node"""
    def __init__(self, name, scene):
        super(Node, self).__init__()
        self.name = name
        self.scene = scene
        self.setFlag(QGraphicsItem.ItemIsMovable)
        self.setFlag(QGraphicsItem.ItemSendsGeometryChanges)

        self.outputs = {}
        self.inputs = {}

        self.setRect(0,0,100,100)
        self.setBrush(QBrush(QColor(100,100,100)))
        self.setPen(QPen(QColor(200,200,200), 0.75))

        # Title bar
        self.title_bar = QGraphicsRectItem(parent=self)
        self.title_bar.setRect(0,0,100,20)
        self.title_bar.setBrush(QBrush(QColor(80,80,100)))
        self.title_bar.setPen(QPen(QColor(200,200,200), 0.75))

        self.label = QGraphicsTextItem(self.name, parent=self)
        self.label.setDefaultTextColor(Qt.white)
        self.label.setTextInteractionFlags(Qt.TextEditable)

    def add_output(self, port):
        port.connector_type = 'output'
        port.setBrush(Qt.blue)
        port.setParentItem(self)
        port.setPos(100,30+15*(len(self.outputs)+len(self.inputs)))
        label = QGraphicsTextItem(port.name, parent=self)
        top_right = label.boundingRect().topRight()
        label.setPos(95-top_right.x(),20+15*(len(self.outputs)+len(self.outputs)))
        label.setDefaultTextColor(Qt.black)
        self.outputs[port.name] = port

    def add_input(self, port):
        port.connector_type = 'input'
        port.setBrush(Qt.green)
        port.setParentItem(self)
        port.setPos(000,30+15*(len(self.inputs)+len(self.outputs)))
        label = QGraphicsTextItem(port.name, parent=self)
        w = label.textWidth()
        label.setPos(5,20+15*(len(self.inputs)+len(self.outputs)))
        label.setDefaultTextColor(Qt.black)
        self.outputs[port.name] = port
        self.inputs[port.name] = port

    def itemChange(self, change, value):
        if change == QGraphicsItem.ItemPositionChange:
            for k, v in self.outputs.items():
                for w in v.wires_out:
                    w.set_start(v.scenePos())
            for k, v in self.inputs.items():
                for w in v.wires_in:
                    w.set_end(v.scenePos())
        return QGraphicsRectItem.itemChange(self, change, value)


    def paint(self, painter, options, widget):
        painter.setBrush(QBrush(QColor(100,100,100)))
        painter.setPen(QPen(QColor(200,200,200), 0.75))
        painter.drawRoundedRect(self.rect(), 5.0, 5.0)

class Wire(QGraphicsPathItem):
    """docstring for Wire"""
    def __init__(self, start_obj, scene):
        self.path = QPainterPath()
        super(Wire, self).__init__(self.path)

        self.scene     = scene
        self.start     = start_obj.scenePos()
        self.end       = self.start
        self.start_obj = start_obj
        self.end_obj   = None
        self.make_path()

        self.setZValue(5)

        self.setPen(QPen(QColor(200,200,200), 0.75))

        # Add endpoint circle
        rad = 5
        self.end_image = QGraphicsEllipseItem(-rad, -rad, 2*rad, 2*rad, parent=self)
        self.end_image.setBrush(Qt.white)
        self.end_image.setPos(self.start)
        self.end_image.setZValue(10)

        # Setup behavior for unlinking the end of the wire, monkeypatch!
        self.end_image.mousePressEvent = lambda e: self.unhook(e)
        self.end_image.mouseMoveEvent = lambda e: self.set_end(e.scenePos())
        self.end_image.mouseReleaseEvent = lambda e: self.decide_drop(e)

    def unhook(self, event):
        self.end_obj.wires_in.remove(self)
        self.start_obj.wires_out.remove(self)

    def decide_drop(self, event):
        self.setVisible(False)
        drop_site = self.scene.itemAt(event.scenePos())
        if isinstance(drop_site, Connector):
            if drop_site.connector_type == 'input':
                print("Good drop!")
                self.set_end(drop_site.scenePos())
                self.setVisible(True)
                self.end_obj = drop_site
                drop_site.wires_in.append(self)
                self.start_obj.wires_out.append(self)
            else:
                print("Can't connect to output")
        else:
            print("Bad drop!")

    def set_start(self, start):
        self.start = start
        self.make_path()

    def set_end(self, end):
        self.end = end
        self.make_path()
        self.end_image.setPos(end)

    def make_path(self):
        self.path = QPainterPath()
        self.path.moveTo(self.start)
        halfway_x = self.start.x() + 0.5*(self.end.x()-self.start.x())
        self.path.cubicTo(halfway_x, self.start.y(), halfway_x, self.end.y(), self.end.x(), self.end.y())
        self.setPath(self.path)
        

class Connector(QGraphicsEllipseItem):
    """docstring for Connector"""
    def __init__(self, name, scene, connector_type='output'):
        self.scene = scene
        rad = 5
        super(Connector, self).__init__(-rad, -rad, 2*rad, 2*rad)
        self.name = name
        self.setBrush(Qt.white)
        self.setPen(Qt.blue)

        self.setZValue(1)

        self.temp_wire = None
        self.wires_in  = []
        self.wires_out = []

        self.connector_type = connector_type

    def mousePressEvent(self, event):
        self.temp_wire = Wire(self, self.scene)
        self.scene.addItem(self.temp_wire)

    def mouseMoveEvent(self, event):
        if self.temp_wire is not None:
            self.temp_wire.set_end(event.scenePos())

    def mouseReleaseEvent(self, event):
        self.temp_wire.decide_drop(event)
   

class NodeCanvas(QGraphicsScene):
    """docstring for NodeCanvas"""
    def __init__(self):
        super(NodeCanvas, self).__init__()
    
    def contextMenuEvent(self, event):
        self.last_click = event.scenePos()

        menu = QMenu()
        awg_menu = menu.addMenu("Filter")
        scope_menu = menu.addMenu("Combine")
        out_menu = menu.addMenu("Output")

        save = QAction('Save to h5', None)
        plot = QAction('Plot to Bokeh-Server', None)
        out_menu.addAction(save)
        out_menu.addAction(plot)
        # testAction = QAction('Test', None)
        save.triggered.connect(self.add_h5)
        # menu.addMenu(testAction)
        menu.exec_(event.screenPos())

    def add_h5(self):
        node = Node("Save to h5", self)
        node.add_input(Connector("Data", self))
        node.setPos(self.last_click)
        self.addItem(node)


if __name__ == "__main__":

    app = QApplication([])

    scene = NodeCanvas()
    scene.setBackgroundBrush(QBrush(QColor(60,60,60)))

    node = Node("Convolve", scene)
    node.add_output(Connector("Output", scene))
    node.add_input(Connector("Waveform", scene))
    node.add_input(Connector("Kernel", scene))
    node.setPos(200,0)
    scene.addItem(node)

    node = Node("Decimate", scene)
    node.add_output(Connector("Output", scene))
    node.add_input(Connector("Waveform", scene))
    node.add_input(Connector("Factor", scene))
    node.setPos(0,0)
    scene.addItem(node)

    node = Node("Data Taker", scene)
    node.add_output(Connector("Output", scene))
    node.setPos(-200,0)
    scene.addItem(node)

    view = QGraphicsView(scene)
    view.setRenderHint(QPainter.Antialiasing)
    view.resize(800, 600)
    view.show()

    # view.window().activateWindow()
    view.window().raise_()
    app.exec_()