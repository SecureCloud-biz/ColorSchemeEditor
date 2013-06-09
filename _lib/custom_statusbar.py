"""
Custom Status Bar
Licensed under MIT
Copyright (c) 2013 Isaac Muse <isaacmuse@gmail.com>
"""
import wx
from collections import OrderedDict
import wx.lib.agw.supertooltip as STT


class ContextMenu(wx.Menu):
    def __init__(self, parent, menu, pos):
        wx.Menu.__init__(self)
        self._callbacks = {}

        for i in menu:
            menuid = wx.NewId()
            item = wx.MenuItem(self, menuid, i[0])
            self._callbacks[menuid] = i[1]
            self.AppendItem(item)
            self.Bind(wx.EVT_MENU, self.on_callback, item)

        parent.PopupMenu(self, pos)

    def on_callback(self, event):
        menuid = event.GetId()
        self._callbacks[menuid](event)


class ToolTip(STT.SuperToolTip):
    def __init__(self, target, message, header="", style="Office 2007 Blue", start_delay=.1):
        super(ToolTip, self).__init__(message, header=header)
        self.SetTarget(target)
        self.ApplyStyle(style)
        self.SetStartDelay(start_delay)
        target.tooltip = self

    def hide(self):
        if self._superToolTip:
            self._superToolTip.Destroy()


class IconTrayExtension(object):
    def remove_icon(self, name):
        if name in self.sb_icons:
            self.hide_tooltip(name)
            self.sb_icons[name].Destroy()
            del self.sb_icons[name]
            self.place_icons(resize=True)

    def hide_tooltip(self, name):
        if self.sb_icons[name].tooltip:
            self.sb_icons[name].tooltip.hide()

    def set_icon(self, name, icon, msg=None, context=None):
        if name in self.sb_icons:
            self.hide_tooltip(name)
            self.sb_icons[name].Destroy()
        self.sb_icons[name] = wx.StaticBitmap(self, bitmap=icon)
        if msg is not None:
            ToolTip(self.sb_icons[name], msg)
        if context is not None:
            self.sb_icons[name].Bind(wx.EVT_RIGHT_DOWN, lambda e: self.show_menu(name, context))
        self.place_icons(resize=True)

    def show_menu(self, name, context):
        self.hide_tooltip(name)
        ContextMenu(self, context, self.sb_icons[name].GetPostion())

    def place_icons(self, resize=False):
        x_offset = 0
        if resize:
            # In wxPython 2.9, the first icon inserted changes the size, additional icons don't
            self.SetStatusWidths([-1, (len(self.sb_icons) - 1) * 20 + 1])
        rect = self.GetFieldRect(1)
        for v in self.sb_icons.values():
            v.SetPosition((rect.x + x_offset, rect.y))
            x_offset += 20

    def on_sb_size(self, event):
        event.Skip()
        self.place_icons()

    def sb_setup(self):
        self.SetFieldsCount(2)
        self.SetStatusText('', 0)
        self.SetStatusWidths([-1, 1])
        self.sb_icons = OrderedDict()
        self.Bind(wx.EVT_SIZE, self.on_sb_size)


class CustomStatusBar(wx.StatusBar, IconTrayExtension):
    def __init__(self, parent):
        super(StatusBarIconTray, self).__init__(parent)
        self.sb_setup()


def extend(instance, extension):
    instance.__class__ = type(
        '%s_extended_with_%s' % (instance.__class__.__name__, extension.__name__),
        (instance.__class__, extension),
        {}
    )


def extend_sb(sb):
    extend(sb, IconTrayExtension)
    sb.sb_setup()
