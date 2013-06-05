 # -*- coding: utf-8 -*-
"""
Color Scheme Editor for Sublime Text
Licensed under MIT
Copyright (c) 2013 Isaac Muse <isaacmuse@gmail.com>
"""
import sys
import argparse
import json
from plistlib import readPlist, writePlistToString
from _lib.file_strip.json import sanitize_json
from codecs import open as codec_open
import wx
import editor
from _lib.rgba import RGBA
import uuid
from os.path import exists, normpath, join, dirname, abspath, basename, isdir
from os import listdir, walk
from _lib.default_new_theme import theme as default_new_theme
from time import sleep, time
import threading
from _lib.custom_app import CustomApp, DebugFrameExtender, init_app_log, set_debug_mode, set_debug_console, get_debug_mode, get_debug_console, debug, info, warning, critical, error
import zipfile
from fnmatch import fnmatch
import re

__version__ = "0.0.9"

BG_COLOR = None
FG_COLOR = None
DEBUG_CONSOLE = False

SUBLIME_PATHS = None

SHORTCUTS = {
    "osx": u'''
===Applicatioon Shortcuts===
Find Next: ⌘ + F
Find Next: ⌘ + G
Find Prev: ⌘ + ⇧ + G
Save: ⌘ + S
Save As: ⌘ + ⇧ + S

===Table Shortcuts===
Edit Row: Enter
Move Row Up (Style Settings): ⌥ + ↑
Move Row Down (Style Settings): ⌥ + ↓
Switch to Global Settings: ⌥ + ←
Switch to Style Settings: ⌥ + →
Delete Row: ⌫
Insert Row: ⌘ + I
Toggle 'bold' font: B
Toggle 'italic' font: I
Toggle 'underlined' font: U
''',

    "windows": u'''
===Applicatioon Shortcuts===
Find Next: Control + F
Find Next: Control + G
Find Prev: Control + Shift + G
Save: Control + S
Save As: Control + Shift + S

===Table Shortcuts===
Edit Row: Enter
Move Row Up (Style Settings): Alt + ↑
Move Row Down (Style Settings): Alt + ↓
Switch to Global Settings: Alt + ←
Switch to Style Settings: Alt + →
Delete Row: Delete
Insert Row: Control + I
Toggle 'bold' font: B
Toggle 'italic' font: I
Toggle 'underlined' font: U
''',

    "linux": u'''
===Applicatioon Shortcuts===
Find Next: Control + F
Find Next: Control + G
Find Prev: Control + Shift + G
Save: Control + S
Save As: Control + Shift + S

===Table Shortcuts===
Edit Row: Enter
Move Row Up (Style Settings): Alt + ↑
Move Row Down (Style Settings): Alt + ↓
Switch to Global Settings: Alt + ←
Switch to Style Settings: Alt + →
Delete Row: Delete
Insert Row: Control + I
Toggle 'bold' font: B
Toggle 'italic' font: I
Toggle 'underlined' font: U
'''
}

JSON_ADD = 1
JSON_DELETE = 2
JSON_MODIFY = 3
JSON_MOVE = 4
JSON_UUID = 5
JSON_NAME = 6


#################################################
# Live Update Manager
#################################################
class LiveUpdate(threading.Thread):
    def __init__(self, func, queue):
        self.func = func
        self.queue = queue
        self.last_queue_len = len(queue)
        self.abort = False
        self.last_update = 0.0
        self.done = False
        self.locked = False
        threading.Thread.__init__(self)

    def kill_thread(self):
        self.abort = True

    def lock_queue(self):
        if not self.is_queue_locked():
            self.locked = True
            return True
        return False

    def release_queue(self):
        if self.is_queue_locked():
            self.locked = False
            return True
        return False

    def is_queue_locked(self):
        return self.locked

    def is_done(self):
        return self.done

    def update(self, queue):
        request = None
        for x in queue:
            if x == "all":
                request = x
                break
            elif x == "json":
                if request == "tmtheme":
                    request = "all"
                else:
                    request = x
            elif x == "tmtheme":
                if request == "json":
                    request = "all"
                    break
                else:
                    request = x

        wx.CallAfter(self.func, request, "Live Thread")

    def _process_queue(self):
        while not self.lock_queue():
            sleep(.2)
        current_queue = self.queue[0:self.last_queue_len]
        del self.queue[0:self.last_queue_len]
        self.last_queue_len = len(self.queue)
        self.release_queue()
        return current_queue

    def run(self):
        while not self.abort:
            now = time()
            if len(self.queue) and (now - .5) > self.last_update:
                if len(self.queue) != self.last_queue_len:
                    self.last_queue_len = len(self.queue)
                else:
                    self.update(self._process_queue())
                    self.last_update = time()
            if self.abort:
                break
            sleep(.5)
        if len(self.queue):
            self.update(self._process_queue())
        self.done = True


#################################################
# Grid Helper Class
#################################################
class GridHelper(object):
    cell_select_semaphore = False
    range_semaphore = False
    current_row = None
    current_col = None

    def setup_keybindings(self):
        deleteid = wx.NewId()
        insertid = wx.NewId()

        self.Bind(wx.EVT_MENU, self.on_delete_row, id=deleteid)
        self.Bind(wx.EVT_MENU, self.on_insert_row, id=insertid)

        accel_tbl = wx.AcceleratorTable(
            [
                (wx.ACCEL_NORMAL, wx.WXK_DELETE, deleteid),
                (wx.ACCEL_CMD, ord('I'), insertid ) if sys.platform == "darwin" else (wx.ACCEL_CTRL, ord('I'), insertid )
            ]
        )
        self.SetAcceleratorTable(accel_tbl)

    def go_cell(self, grid, row, col, focus=False):
        if focus:
            grid.GoToCell(row, col)
        else:
            grid.SetGridCursor(row, col)
        bg = grid.GetCellBackgroundColour(row, 0)
        lum = RGBA(bg.GetAsString(wx.C2S_HTML_SYNTAX)).luminance()
        if lum > 128:
            bg.Set(0, 0, 0)
        else:
            bg.Set(255, 255, 255)
        grid.SetCellHighlightColour(bg)

    def mouse_motion(self, event):
        if event.Dragging():       # mouse being dragged?
            pass                   # eat the event
        else:
            event.Skip()           # no dragging, pass on to the window

    def grid_key_down(self, event):
        no_modifiers = event.GetModifiers() == 0
        alt_mod = event.GetModifiers() == wx.MOD_ALT
        if no_modifiers and event.GetKeyCode() == ord('B'):
            self.toggle_bold()
            return
        elif no_modifiers and event.GetKeyCode() == ord('I'):
            self.toggle_italic()
            return
        elif no_modifiers and event.GetKeyCode() == ord('U'):
            self.toggle_underline()
            return
        elif no_modifiers and event.GetKeyCode() == wx.WXK_RETURN:
            self.edit_cell()
            return
        elif alt_mod and event.GetKeyCode() == wx.WXK_UP:
            self.row_up()
            return
        elif alt_mod and event.GetKeyCode() == wx.WXK_DOWN:
            self.row_down()
            return
        elif alt_mod and event.GetKeyCode() == wx.WXK_LEFT:
            self.on_panel_left(event)
            return
        elif alt_mod and event.GetKeyCode() == wx.WXK_RIGHT:
            self.on_panel_right(event)
            return
        elif event.AltDown():
            # Eat...NOM NOM
            if event.GetKeyCode() == wx.WXK_UP:
                return
            elif event.GetKeyCode() == wx.WXK_DOWN:
                return
            elif event.GetKeyCode() == wx.WXK_LEFT:
                return
            elif event.GetKeyCode() == wx.WXK_RIGHT:
                return
        elif event.ShiftDown():
            # Eat...NOM NOM
            if event.GetKeyCode() == wx.WXK_UP:
                return
            elif event.GetKeyCode() == wx.WXK_DOWN:
                return
            elif event.GetKeyCode() == wx.WXK_LEFT:
                return
            elif event.GetKeyCode() == wx.WXK_RIGHT:
                return
        event.Skip()

    def grid_select_cell(self, event):
        grid = self.m_plist_grid
        if not self.cell_select_semaphore and event.Selecting():
            self.cell_select_semaphore = True
            self.current_row = event.GetRow()
            self.current_col = event.GetCol()
            self.go_cell(grid, self.current_row, self.current_col)
            self.cell_select_semaphore = False
        event.Skip()

    def on_panel_left(self, event):
        grid = self.m_plist_grid
        grid.GetParent().GetParent().ChangeSelection(0)
        grid.GetParent().GetParent().GetPage(0).m_plist_grid.SetFocus()

    def on_panel_right(self, event):
        grid = self.m_plist_grid
        grid.GetParent().GetParent().ChangeSelection(1)
        grid.GetParent().GetParent().GetPage(1).m_plist_grid.SetFocus()

    def on_row_up(self, event):
        self.row_up()

    def on_row_down(self, event):
        self.row_down()

    def on_insert_row(self, event):
        self.insert_row()

    def on_delete_row(self, event):
        self.delete_row()

    def on_edit_cell_key(self, event):
        self.edit_cell()

    def on_toggle_bold(self, event):
        self.toggle_bold()

    def on_toggle_italic(self, event):
        self.toggle_italic()

    def on_toggle_underline(self, event):
        self.toggle_underline()

    def toggle_bold(self):
        pass

    def toggle_italic(self):
        pass

    def toggle_underline(self):
        pass

    def row_up(self):
        pass

    def row_down(self):
        pass

    def edit_cell(self):
        pass

    def delete_row(self):
        pass

    def insert_row(self):
        pass


#################################################
# Grid Display Panels
#################################################
class StyleSettings(editor.StyleSettingsPanel, GridHelper):
    def __init__(self, parent, scheme, update):
        super(StyleSettings, self).__init__(parent)
        self.setup_keybindings()
        self.parent = parent
        wx.EVT_MOTION(self.m_plist_grid.GetGridWindow(), self.on_mouse_motion)
        self.m_plist_grid.SetDefaultCellBackgroundColour(self.GetBackgroundColour())
        self.read_plist(scheme)
        self.update_plist = update

    def read_plist(self, scheme):
        foreground = RGBA(scheme["settings"][0]["settings"].get("foreground", "#000000"))
        background = RGBA(scheme["settings"][0]["settings"].get("background", "#FFFFFF"))
        global BG_COLOR
        BG_COLOR = background
        global FG_COLOR
        FG_COLOR = foreground
        count = 0

        for s in scheme["settings"]:
            if "name" in s:
                self.m_plist_grid.AppendRows(1)
                self.update_row(count, s)
                count += 1
        self.resize_table()
        self.go_cell(self.m_plist_grid, 0, 0)

    def update_row(self, count, s):
        self.m_plist_grid.SetCellValue(count, 0, s["name"])
        self.m_plist_grid.SetCellValue(count, 4, s.get("scope", ""))
        settings = s["settings"]
        b = self.m_plist_grid.GetCellBackgroundColour(count, 0)
        if "background" in settings:
            try:
                bg = RGBA(settings["background"].strip())
                bg.apply_alpha(BG_COLOR.get_rgb())
                self.m_plist_grid.SetCellValue(count, 2, settings["background"])
            except:
                bg = BG_COLOR
                self.m_plist_grid.SetCellValue(count, 2, "")
        else:
            bg = BG_COLOR
        b = self.m_plist_grid.GetCellBackgroundColour(count, 0)
        b.Set(bg.r, bg.g, bg.b)
        self.m_plist_grid.SetCellBackgroundColour(count, 0, b)
        self.m_plist_grid.SetCellBackgroundColour(count, 1, b)
        self.m_plist_grid.SetCellBackgroundColour(count, 2, b)
        self.m_plist_grid.SetCellBackgroundColour(count, 3, b)
        self.m_plist_grid.SetCellBackgroundColour(count, 4, b)
        if "foreground" in settings:
            try:
                fg = RGBA(settings["foreground"].strip())
                fg.apply_alpha(BG_COLOR.get_rgb())
                self.m_plist_grid.SetCellValue(count, 1, settings["foreground"])
            except:
                fg = FG_COLOR
                self.m_plist_grid.SetCellValue(count, 1, "")
        else:
            fg = FG_COLOR
        f = self.m_plist_grid.GetCellTextColour(count, 0)
        f.Set(fg.r, fg.g, fg.b)
        self.m_plist_grid.SetCellTextColour(count, 0, f)
        self.m_plist_grid.SetCellTextColour(count, 1, f)
        self.m_plist_grid.SetCellTextColour(count, 2, f)
        self.m_plist_grid.SetCellTextColour(count, 3, f)
        self.m_plist_grid.SetCellTextColour(count, 4, f)

        fs_setting = settings.get("fontStyle", "")
        font_style = []
        for x in fs_setting.split(" "):
            if x in ["bold", "italic", "underline"]:
                font_style.append(x)

        self.m_plist_grid.SetCellValue(count, 3, " ".join(font_style))
        fs = self.m_plist_grid.GetCellFont(count, 0)
        fs.SetWeight(wx.FONTWEIGHT_NORMAL)
        fs.SetStyle(wx.FONTSTYLE_NORMAL)
        fs.SetUnderlined(False)

        if "bold" in font_style:
            fs.SetWeight(wx.FONTWEIGHT_BOLD)

        if "italic" in font_style:
            fs.SetStyle(wx.FONTSTYLE_ITALIC)

        if "underline" in font_style:
            fs.SetUnderlined(True)

        self.m_plist_grid.SetCellFont(count, 0, fs)
        self.m_plist_grid.SetCellFont(count, 1, fs)
        self.m_plist_grid.SetCellFont(count, 2, fs)
        self.m_plist_grid.SetCellFont(count, 3, fs)
        self.m_plist_grid.SetCellFont(count, 4, fs)

    def resize_table(self):
        self.m_plist_grid.BeginBatch()
        nb_size = self.parent.GetSize()
        total_size = 0
        for x in range(0, 5):
            self.m_plist_grid.AutoSizeColumn(x)
            total_size += self.m_plist_grid.GetColSize(x)
        delta = nb_size[0] - 20 - total_size
        if delta > 0:
            self.m_plist_grid.SetColSize(4, self.m_plist_grid.GetColSize(4) + delta)
        self.m_plist_grid.EndBatch()

    def set_object(self, obj):
        row = self.m_plist_grid.GetGridCursorRow()
        col = self.m_plist_grid.GetGridCursorCol()
        self.update_row(row, obj)
        self.update_plist(JSON_MODIFY, {"table": "style", "index": row, "data": obj})
        self.resize_table()

    def edit_cell(self):
        grid = self.m_plist_grid
        row = grid.GetGridCursorRow()
        editor = self.GetParent().GetParent().GetParent()
        ColorEditor(
            editor,
            {
                "name": grid.GetCellValue(row, 0),
                "scope": grid.GetCellValue(row, 4),
                "settings": {
                    "foreground": grid.GetCellValue(row, 1),
                    "background": grid.GetCellValue(row, 2),
                    "fontStyle": grid.GetCellValue(row, 3)
                }
            }
        ).ShowModal()

    def delete_row(self):
        row = self.m_plist_grid.GetGridCursorRow()
        col = self.m_plist_grid.GetGridCursorCol()
        self.m_plist_grid.DeleteRows(row, 1)
        name = self.m_plist_grid.GetCellValue(row, 0)
        self.m_plist_grid.GetParent().update_plist(JSON_DELETE, {"table": "style", "index": row})

    def insert_row(self):
        obj = {
            "name": "New Item",
            "scope": "comment",
            "settings": {
                "foreground": "#FFFFFF",
                "background": "#000000",
                "fontStyle": ""
            }
        }
        editor = self.GetParent().GetParent().GetParent()
        ColorEditor(
            editor,
            obj,
            insert=True
        ).ShowModal()

    def row_up(self):
        grid = self.m_plist_grid
        row = grid.GetGridCursorRow()
        col = grid.GetGridCursorCol()
        if row > 0:
            text = [grid.GetCellValue(row, x) for x in range(0, 5)]
            bg = [grid.GetCellBackgroundColour(row, x) for x in range(0, 5)]
            fg = [grid.GetCellTextColour(row, x) for x in range(0, 5)]
            font = [grid.GetCellFont(row, x) for x in range(0, 5)]
            grid.DeleteRows(row, 1, False)
            grid.InsertRows(row - 1, 1, True)
            [grid.SetCellValue(row - 1, x, text[x]) for x in range(0, 5)]
            [grid.SetCellBackgroundColour(row - 1, x, bg[x]) for x in range(0, 5)]
            [grid.SetCellTextColour(row - 1, x, fg[x]) for x in range(0, 5)]
            [grid.SetCellFont(row - 1, x, font[x]) for x in range(0, 5)]
            self.go_cell(grid, row - 1, col, True)
            grid.GetParent().update_plist(JSON_MOVE, {"from": row, "to": row - 1})
            grid.SetFocus()

    def row_down(self):
        grid = self.m_plist_grid
        row = grid.GetGridCursorRow()
        col = grid.GetGridCursorCol()
        if row < grid.GetNumberRows() - 1:
            text = [grid.GetCellValue(row, x) for x in range(0, 5)]
            bg = [grid.GetCellBackgroundColour(row, x) for x in range(0, 5)]
            fg = [grid.GetCellTextColour(row, x) for x in range(0, 5)]
            font = [grid.GetCellFont(row, x) for x in range(0, 5)]
            grid.DeleteRows(row, 1, False)
            grid.InsertRows(row + 1, 1, True)
            [grid.SetCellValue(row + 1, x, text[x]) for x in range(0, 5)]
            [grid.SetCellBackgroundColour(row + 1, x, bg[x]) for x in range(0, 5)]
            [grid.SetCellTextColour(row + 1, x, fg[x]) for x in range(0, 5)]
            [grid.SetCellFont(row + 1, x, font[x]) for x in range(0, 5)]
            self.go_cell(grid, row + 1, col, True)
            grid.GetParent().update_plist(JSON_MOVE, {"from": row, "to": row + 1})
            grid.SetFocus()

    def is_fontstyle_cell(self):
        return self.m_plist_grid.GetGridCursorCol() == 3

    def toggle_font_style(self, row, attr):
        # if not self.is_fontstyle_cell():
        #     return
        grid = self.m_plist_grid
        text = [grid.GetCellValue(row, x) for x in range(0, 5)]
        style = text[3].split(" ")
        try:
            idx = style.index(attr)
            del style[idx]
        except:
            style.append(attr)
        text[3] = " ".join(style)

        obj = {
            "name": text[0],
            "scope": text[4],
            "settings": {
                "foreground": text[1],
                "background": text[2],
                "fontStyle": text[3]
            }
        }
        grid.GetParent().update_row(row, obj)
        self.update_plist(JSON_MODIFY, {"table": "style", "index": row, "data": obj})
        self.resize_table()

    def toggle_bold(self):
        self.toggle_font_style(self.m_plist_grid.GetGridCursorRow(), "bold")

    def toggle_italic(self):
        self.toggle_font_style(self.m_plist_grid.GetGridCursorRow(), "italic")

    def toggle_underline(self):
        self.toggle_font_style(self.m_plist_grid.GetGridCursorRow(), "underline")

    def on_mouse_motion(self, event):
        self.mouse_motion(event)

    def on_edit_cell(self, event):
        self.edit_cell()

    def on_grid_key_down(self, event):
        self.grid_key_down(event)

    def on_grid_select_cell(self, event):
        self.grid_select_cell(event)

    def on_row_up_click(self, event):
        self.row_up()

    def on_row_down_click(self, event):
        self.row_down()

    def on_row_add_click(self, event):
        self.insert_row()

    def on_row_delete_click(self, event):
        self.delete_row()

    def on_grid_label_left_click(self, event):
        return


class GlobalSettings(editor.GlobalSettingsPanel, GridHelper):
    def __init__(self, parent, scheme, update, reshow):
        super(GlobalSettings, self).__init__(parent)
        self.setup_keybindings()
        self.parent = parent
        wx.EVT_MOTION(self.m_plist_grid.GetGridWindow(), self.on_mouse_motion)
        self.m_plist_grid.SetDefaultCellBackgroundColour(self.GetBackgroundColour())
        self.read_plist(scheme)
        self.reshow = reshow
        self.update_plist = update

    def read_plist(self, scheme):
        foreground = RGBA(scheme["settings"][0]["settings"].get("foreground", "#000000"))
        background = RGBA(scheme["settings"][0]["settings"].get("background", "#FFFFFF"))
        global BG_COLOR
        BG_COLOR = background
        global FG_COLOR
        FG_COLOR = foreground
        count = 0

        for k in sorted(scheme["settings"][0]["settings"].iterkeys()):
            v = scheme["settings"][0]["settings"][k]
            self.m_plist_grid.AppendRows(1)
            self.update_row(count, k, v)
            count += 1
        self.resize_table()

        self.go_cell(self.m_plist_grid, 0, 0)

    def resize_table(self):
        self.m_plist_grid.BeginBatch()
        nb_size = self.parent.GetSize()
        total_size = 0
        for x in range(0, 2):
            self.m_plist_grid.AutoSizeColumn(x)
            total_size += self.m_plist_grid.GetColSize(x)
        delta = nb_size[0] - 20 - total_size
        if delta > 0:
            self.m_plist_grid.SetColSize(1, self.m_plist_grid.GetColSize(1) + delta)
        self.m_plist_grid.EndBatch()

    def update_row(self, count, k, v):
        try:
            bg = RGBA(v.strip())
            if k != "background":
                bg.apply_alpha(BG_COLOR.get_rgb())
            fg = RGBA("#000000") if bg.luminance() > 128 else RGBA("#FFFFFF")
        except:
            bg = RGBA("#FFFFFF")
            fg = RGBA("#000000")

        self.m_plist_grid.SetCellValue(count, 0, k)
        self.m_plist_grid.SetCellValue(count, 1, v)

        b = self.m_plist_grid.GetCellBackgroundColour(count, 0)
        f = self.m_plist_grid.GetCellTextColour(count, 0)

        b.Set(bg.r, bg.g, bg.b)
        f.Set(fg.r, fg.g, fg.b)

        self.m_plist_grid.SetCellBackgroundColour(count, 0, b)
        self.m_plist_grid.SetCellBackgroundColour(count, 1, b)

        self.m_plist_grid.SetCellTextColour(count, 0, f)
        self.m_plist_grid.SetCellTextColour(count, 1, f)

    def set_object(self, key, value):
        row = self.m_plist_grid.GetGridCursorRow()
        col = self.m_plist_grid.GetGridCursorCol()
        self.update_row(row, key, value)
        self.update_plist(JSON_MODIFY, {"table": "global", "index": key, "data": value})
        if key == "background" or key == "foreground":
            self.reshow(row, col)
        self.resize_table()

    def delete_row(self):
        row = self.m_plist_grid.GetGridCursorRow()
        col = self.m_plist_grid.GetGridCursorCol()
        name = self.m_plist_grid.GetCellValue(row, 0)
        self.m_plist_grid.DeleteRows(row, 1)
        self.m_plist_grid.GetParent().update_plist(JSON_DELETE, {"table": "global", "index": name})
        if name == "foreground" or name == "background":
            self.m_plist_grid.GetParent().reshow(row, col)

    def validate_name(self, name):
        valid = True
        editor = self.GetParent().GetParent().GetParent()
        for k in editor.scheme["settings"][0]["settings"]:
            if name == k:
                valid = False
                break
        return valid

    def insert_row(self):
        new_name = "new_item"
        count = 0
        while not self.validate_name(new_name):
            new_name = "new_item_%d" % count
            count += 1

        editor = self.GetParent().GetParent().GetParent()
        GlobalEditor(
            editor,
            editor.scheme["settings"][0]["settings"],
            new_name,
            "nothing",
            insert=True
        ).ShowModal()

    def edit_cell(self):
        grid = self.m_plist_grid
        row = grid.GetGridCursorRow()
        editor = self.GetParent().GetParent().GetParent()
        GlobalEditor(
            editor,
            editor.scheme["settings"][0]["settings"],
            grid.GetCellValue(row, 0),
            grid.GetCellValue(row, 1)
        ).ShowModal()

    def on_grid_label_left_click(self, event):
        return

    def on_mouse_motion(self, event):
        self.mouse_motion(event)

    def on_edit_cell(self, event):
        self.edit_cell()

    def on_grid_key_down(self, event):
        self.grid_key_down(event)

    def on_grid_select_cell(self, event):
        self.grid_select_cell(event)

    def on_row_add_click(self, event):
        self.insert_row()

    def on_row_delete_click(self, event):
        self.delete_row()


#################################################
# Settings Dialogs
#################################################
class SettingsKeyBindings(object):
    def setup_keybindings(self):
        self.Bind(wx.EVT_CHAR_HOOK, self.on_char_hook)

    def on_char_hook(self, event):
        if event.GetKeyCode() == wx.WXK_ESCAPE:
            self.Close()
        event.Skip()


class GlobalEditor(editor.GlobalSetting, SettingsKeyBindings):
    def __init__(self, parent, current_entries, name, value, insert=False):
        super(GlobalEditor, self).__init__(parent)
        self.setup_keybindings()
        self.Fit()
        size = self.GetSize()
        self.SetMinSize(size)
        size.Set(-1, size[1])
        self.SetMaxSize(size)
        self.obj_key = name
        self.obj_val = value
        self.color_save = ""
        self.apply_settings = False
        self.color_setting = False
        self.m_color_picker.Disable()
        self.entries = current_entries
        self.current_name = name
        self.valid = True
        self.insert = bool(insert)

        self.m_name_textbox.SetValue(self.obj_key)
        try:
            RGBA(self.obj_val)
            self.color_setting = True
            self.color_save = self.obj_val
            self.m_color_picker.Enable()
            self.m_color_checkbox.SetValue(True)
        except:
            pass
        self.m_value_textbox.SetValue(self.obj_val)

    def on_color_button_click(self, event):
        if not self.color_setting:
            event.Skip()
            return
        color = None
        data = wx.ColourData()
        data.SetChooseFull(True)

        alpha = None

        text = self.m_value_textbox.GetValue()
        rgb = RGBA(text)
        if len(text) == 9:
            alpha == text[7:9]

        # set the default color in the chooser
        data.SetColour(wx.Colour(rgb.r, rgb.g, rgb.b))

        # construct the chooser
        dlg = wx.ColourDialog(self, data)

        if dlg.ShowModal() == wx.ID_OK:
            # set the panel background color
            color = dlg.GetColourData().GetColour().GetAsString(wx.C2S_HTML_SYNTAX)
            self.m_value_textbox.SetValue(color if alpha is None else color + alpha)
        dlg.Destroy()
        event.Skip()

    def on_global_checkbox(self, event):
        if event.IsChecked():
            self.m_color_picker.Enable()
            self.color_setting = True
            try:
                RGBA(self.m_value_textbox.GetValue())
                self.on_color_change(event)
            except:
                self.m_value_textbox.SetValue("#000000")
            return
        else:
            self.color_setting = False
            self.m_color_picker.Disable()
            self.m_color_picker.SetBackgroundColour(wx.Colour(255, 255, 255))
            self.m_color_picker.Refresh()
        event.Skip()

    def is_name_valid(self):
        valid = True
        name = self.m_name_textbox.GetValue()
        if name != self.current_name:
            for k in self.entries:
                if name == k:
                    valid = False
                    break
        return valid

    def on_global_name_blur(self, event):
        if not self.is_name_valid():
            errormsg("Key name \"%s\" already exists in global settings. Please use a different name." % self.m_name_textbox.GetValue())
            self.m_name_textbox.SetValue(self.current_name)
        else:
            self.current_name = self.m_name_textbox.GetValue()

    def on_color_change(self, event):
        if not self.color_setting:
            event.Skip()
            return
        text = self.m_value_textbox.GetValue()
        try:
            cl = RGBA(text)
        except:
            event.Skip()
            return

        cl.apply_alpha(BG_COLOR.get_rgb())
        bg = wx.Colour(cl.r, cl.g, cl.b)
        self.m_color_picker.SetBackgroundColour(bg)
        self.m_color_picker.Refresh()

    def on_color_focus(self, event):
        if not self.color_setting:
            event.Skip()
            return
        if self.color_setting:
            self.color_save = self.m_value_textbox.GetValue()
        event.Skip()

    def on_color_blur(self, event):
        if not self.color_setting:
            event.Skip()
            return
        if self.color_setting:
            text = self.m_value_textbox.GetValue()
            try:
                RGBA(text)
            except:
                self.m_value_textbox.SetValue(self.color_save)
        event.Skip()

    def on_apply_button_click(self, event):
        self.m_apply_button.SetFocus()
        if self.is_name_valid():
            self.apply_settings = True
            self.Close()
        else:
            errormsg("Key name \"%s\" already exists in global settings. Please use a different name." % self.m_name_textbox.GetValue())
            self.m_name_textbox.SetValue(self.current_name)

    def on_set_color_close(self, event):
        self.obj_key = self.m_name_textbox.GetValue()
        self.current_name = self.obj_key

        if self.apply_settings:
            self.obj_val = self.m_value_textbox.GetValue()

            if self.insert:
                grid = self.Parent.m_global_settings.m_plist_grid
                num = grid.GetNumberRows()
                row = grid.GetGridCursorRow()
                if num > 0:
                    grid.InsertRows(row, 1, True)
                else:
                    grid.AppendRows(1)
                    row = 0
                grid.GetParent().update_row(row, self.obj_key, self.obj_val)
                grid.GetParent().go_cell(grid, row, 0)
                self.Parent.update_plist(JSON_ADD, {"table": "global", "index": self.obj_key, "data": self.obj_val})
            else:
                self.Parent.set_global_object(self.obj_key, self.obj_val)

        event.Skip()


class ColorEditor(editor.ColorSetting, SettingsKeyBindings):
    def __init__(self, parent, obj, insert=False):
        super(ColorEditor, self).__init__(parent)
        self.setup_keybindings()
        self.Fit()
        size = self.GetSize()
        self.SetMinSize(size)
        size.Set(-1, size[1])
        self.SetMaxSize(size)
        self.foreground_save = ""
        self.background_save = ""
        self.apply_settings = False
        self.color_obj = obj
        self.insert = bool(insert)

        self.m_bold_checkbox.SetValue(False)
        self.m_italic_checkbox.SetValue(False)
        self.m_underline_checkbox.SetValue(False)

        for x in self.color_obj["settings"]["fontStyle"].split(" "):
            if x == "bold":
                self.m_bold_checkbox.SetValue(True)
            elif x == "italic":
                self.m_italic_checkbox.SetValue(True)
            elif x == "underline":
                self.m_underline_checkbox.SetValue(True)

        self.m_name_textbox.SetValue(self.color_obj["name"])
        self.m_scope_textbox.SetValue(self.color_obj["scope"])

        self.m_foreground_textbox.SetValue(self.color_obj["settings"]["foreground"])
        if self.color_obj["settings"]["foreground"] == "":
            cl = RGBA("#FFFFFF")
            bg = wx.Colour(cl.r, cl.g, cl.b)
            self.m_foreground_picker.SetBackgroundColour(bg)
            if cl.luminance() > 128:
                fg = wx.Colour(0, 0, 0)
            else:
                fg = wx.Colour(255, 255, 255)
            self.m_foreground_button_label.SetForegroundColour(fg)

        self.m_background_textbox.SetValue(self.color_obj["settings"]["background"])
        if self.color_obj["settings"]["background"] == "":
            cl = RGBA("#FFFFFF")
            bg = wx.Colour(cl.r, cl.g, cl.b)
            self.m_background_picker.SetBackgroundColour(bg)
            if cl.luminance() > 128:
                fg = wx.Colour(0, 0, 0)
            else:
                fg = wx.Colour(255, 255, 255)
            self.m_background_button_label.SetForegroundColour(fg)

    def on_foreground_button_click(self, event):
        color = None
        data = wx.ColourData()
        data.SetChooseFull(True)

        alpha = None

        text = self.m_foreground_textbox.GetValue()
        if text == "":
            rgb = RGBA("#FFFFFF")
        else:
            rgb = RGBA(text)
            if len(text) == 9:
                alpha == text[7:9]

        # set the default color in the chooser
        data.SetColour(wx.Colour(rgb.r, rgb.g, rgb.b))

        # construct the chooser
        dlg = wx.ColourDialog(self, data)

        if dlg.ShowModal() == wx.ID_OK:
            # set the panel background color
            color = dlg.GetColourData().GetColour().GetAsString(wx.C2S_HTML_SYNTAX)
            self.m_foreground_textbox.SetValue(color if alpha is None else color + alpha)
        dlg.Destroy()
        event.Skip()

    def on_background_button_click(self, event):
        color = None
        data = wx.ColourData()
        data.SetChooseFull(True)

        alpha = None

        text = self.m_background_textbox.GetValue()
        if text == "":
            rgb = RGBA("#FFFFFF")
        else:
            rgb = RGBA(text)
            if len(text) == 9:
                alpha == text[7:9]

        # set the default color in the chooser
        data.SetColour(wx.Colour(rgb.r, rgb.g, rgb.b))

        # construct the chooser
        dlg = wx.ColourDialog(self, data)

        if dlg.ShowModal() == wx.ID_OK:
            # set the panel background color
            color = dlg.GetColourData().GetColour().GetAsString(wx.C2S_HTML_SYNTAX)
            self.m_background_textbox.SetValue(color if alpha is None else color + alpha)
        dlg.Destroy()
        event.Skip()

    def on_background_change(self, event):
        text = self.m_background_textbox.GetValue()
        try:
            if text == "":
                cl = RGBA("#FFFFFF")
            else:
                cl = RGBA(text)
        except:
            event.Skip()
            return

        cl.apply_alpha(BG_COLOR.get_rgb())
        bg = wx.Colour(cl.r, cl.g, cl.b)
        self.m_background_picker.SetBackgroundColour(bg)
        if cl.luminance() > 128:
            fg = wx.Colour(0, 0, 0)
        else:
            fg = wx.Colour(255, 255, 255)
        self.m_background_button_label.SetForegroundColour(fg)
        self.m_background_picker.Refresh()

    def on_foreground_change(self, event):
        text = self.m_foreground_textbox.GetValue()
        try:
            if text == "":
                cl = RGBA("#FFFFFF")
            else:
                cl = RGBA(text)
        except:
            event.Skip()
            return

        cl.apply_alpha(BG_COLOR.get_rgb())
        bg = wx.Colour(cl.r, cl.g, cl.b)
        self.m_foreground_picker.SetBackgroundColour(bg)
        if cl.luminance() > 128:
            fg = wx.Colour(0, 0, 0)
        else:
            fg = wx.Colour(255, 255, 255)
        self.m_foreground_button_label.SetForegroundColour(fg)
        self.m_foreground_picker.Refresh()

    def on_foreground_focus(self, event):
        self.foreground_save = self.m_foreground_textbox.GetValue()
        event.Skip()

    def on_background_focus(self, event):
        self.background_save = self.m_background_textbox.GetValue()
        event.Skip()

    def on_foreground_blur(self, event):
        text = self.m_foreground_textbox.GetValue()
        if text != "":
            try:
                RGBA(text)
            except:
                self.m_foreground_textbox.SetValue(self.foreground_save)
        event.Skip()

    def on_background_blur(self, event):
        text = self.m_background_textbox.GetValue()
        if text != "":
            try:
                RGBA(text)
            except:
                self.m_background_textbox.SetValue(self.background_save)
        event.Skip()

    def on_apply_button_click(self, event):
        self.apply_settings = True
        self.Close()

    def on_set_color_close(self, event):
        fontstyle = []
        if self.m_bold_checkbox.GetValue():
            fontstyle.append("bold")
        if self.m_italic_checkbox.GetValue():
            fontstyle.append("italic")
        if self.m_underline_checkbox.GetValue():
            fontstyle.append("underline")

        if self.apply_settings:
            self.color_obj = {
                "name": self.m_name_textbox.GetValue(),
                "scope": self.m_scope_textbox.GetValue(),
                "settings": {
                    "foreground": self.m_foreground_textbox.GetValue(),
                    "background": self.m_background_textbox.GetValue(),
                    "fontStyle": " ".join(fontstyle)
                }
            }

            if self.insert:
                grid = self.Parent.m_style_settings.m_plist_grid
                num = grid.GetNumberRows()
                row = grid.GetGridCursorRow()
                if num > 0:
                    grid.InsertRows(row, 1, True)
                else:
                    grid.AppendRows(1)
                    row = 0
                grid.GetParent().update_row(row, self.color_obj)
                grid.GetParent().go_cell(grid, row, 0)
                self.Parent.update_plist(JSON_ADD, {"table": "style", "index": row, "data": self.color_obj})
            else:
                self.Parent.set_style_object(self.color_obj)
        event.Skip()


#################################################
# Editor Dialog
#################################################
class Editor(editor.EditorFrame, DebugFrameExtender):
    def __init__(self, parent, scheme, j_file, t_file, live_save, debugging=False):
        super(Editor, self).__init__(parent)
        findid = wx.NewId()
        findnextid = wx.NewId()
        findprevid = wx.NewId()
        saveasid = wx.NewId()
        saveid = wx.NewId()
        scid = wx.NewId()
        self.live_save = bool(live_save)
        self.updates_made = False
        mod = wx.ACCEL_CMD if sys.platform == "darwin" else wx.ACCEL_CTRL
        self.set_keybindings(
            [
                (mod, ord('B'), self.on_shortcuts),
                (mod|wx.ACCEL_SHIFT, ord('S'), self.on_save_as),
                (mod, ord('S'), self.on_save),
                (mod,  ord('F'), self.focus_find ),
                (mod, ord('G'), self.on_next_find),
                (mod|wx.ACCEL_SHIFT, ord('G'), self.on_prev_find)
            ],
            self.on_debug_console if debugging else None
        )
        if debugging:
            self.open_debug_console()
        self.SetTitle("Color Scheme Editor - %s" % basename(t_file))
        self.search_results = []
        self.cur_search = None
        self.last_UUID = None
        self.last_plist_name = None
        self.scheme = scheme
        self.json = j_file
        self.tmtheme = t_file
        debug(scheme, fmt=lambda x: json.dumps(self.scheme, sort_keys=True, indent=4, separators=(',', ': ')))

        try:
            self.m_global_settings = GlobalSettings(self.m_plist_notebook, scheme, self.update_plist, self.rebuild_tables)
            self.m_style_settings = StyleSettings(self.m_plist_notebook, scheme, self.update_plist)
        except Exception as e:
            debug("Failed to load scheme settings!")
            debug(e)
            raise

        self.m_plist_name_textbox.SetValue(scheme["name"])
        self.m_plist_uuid_textbox.SetValue(scheme["uuid"])
        self.last_UUID = scheme["uuid"]
        self.last_plist_name = scheme["name"]

        self.m_menuitem_save.Enable(False)

        self.m_plist_notebook.InsertPage(0, self.m_global_settings, "Global Settings", True)
        self.m_plist_notebook.InsertPage(1, self.m_style_settings, "Scope Settings", False)
        self.queue = []
        if self.live_save:
            self.update_thread = LiveUpdate(self.save, self.queue)
            self.update_thread.start()

    def update_plist(self, code, args={}):
        if code == JSON_UUID:
            self.scheme["uuid"] = self.m_plist_uuid_textbox.GetValue()
            self.updates_made = True
        elif code == JSON_NAME:
            self.scheme["name"] = self.m_plist_name_textbox.GetValue()
            self.updates_made = True
        elif code == JSON_ADD and args is not None:
            debug("JSON add")
            if args["table"] == "style":
                self.scheme["settings"].insert(args["index"] + 1, args["data"])
            else:
                self.scheme["settings"][0]["settings"][args["index"]] = args["data"]
            self.updates_made = True
        elif code == JSON_DELETE and args is not None:
            debug("JSON delete")
            if args["table"] == "style":
                del self.scheme["settings"][args["index"] + 1]
            else:
                del self.scheme["settings"][0]["settings"][args["index"]]
            self.updates_made = True
        elif code == JSON_MOVE and args is not None:
            debug("JSON move")
            from_row = args["from"] + 1
            to_row = args["to"] + 1
            item = self.scheme["settings"][from_row]
            del self.scheme["settings"][from_row]
            self.scheme["settings"].insert(to_row, item)
            self.updates_made = True
        elif code == JSON_MODIFY and args is not None:
            debug("JSON modify")
            if args["table"] == "style":
                obj = {
                    "name": args["data"]["name"],
                    "scope": args["data"]["scope"],
                    "settings": {
                    }
                }

                settings = args["data"]["settings"]

                if settings["foreground"] != "":
                    obj["settings"]["foreground"] = settings["foreground"]

                if settings["background"] != "":
                    obj["settings"]["background"] = settings["background"]

                if settings["fontStyle"] != "":
                    obj["settings"]["fontStyle"] = settings["fontStyle"]

                self.scheme["settings"][args["index"] + 1] = obj
            else:
                self.scheme["settings"][0]["settings"][args["index"]] = args["data"]
            self.updates_made = True
        else:
            debug("No valid edit actions!")

        if self.live_save:
            while not self.update_thread.lock_queue():
                sleep(.2)
            self.queue.append("tmtheme")
            self.update_thread.release_queue()
        elif self.updates_made:
            self.m_menuitem_save.Enable(True)

    def rebuild_plist(self):
        self.scheme["name"] = self.m_plist_name_textbox.GetValue()
        self.scheme["uuid"] = self.m_plist_uuid_textbox.GetValue()
        self.scheme["settings"] = [{"settings": {}}]
        for r in range(0, self.m_global_settings.m_plist_grid.GetNumberRows()):
            key = self.m_global_settings.m_plist_grid.GetCellValue(r, 0)
            val = self.m_global_settings.m_plist_grid.GetCellValue(r, 1)
            self.scheme["settings"][0]["settings"][key] = val

        for r in range(0, self.m_style_settings.m_plist_grid.GetNumberRows()):
            name = self.m_style_settings.m_plist_grid.GetCellValue(r, 0)
            foreground = self.m_style_settings.m_plist_grid.GetCellValue(r, 1)
            background = self.m_style_settings.m_plist_grid.GetCellValue(r, 2)
            fontstyle = self.m_style_settings.m_plist_grid.GetCellValue(r, 3)
            scope = self.m_style_settings.m_plist_grid.GetCellValue(r, 4)

            obj = {
                "name": name,
                "scope": scope,
                "settings": {
                }
            }

            if foreground != "":
                obj["settings"]["foreground"] = foreground

            if background != "":
                obj["settings"]["background"] = background

            if fontstyle != "":
                obj["settings"]["fontStyle"] = fontstyle

            self.scheme["settings"].append(obj)

        if self.live_save:
            while not self.update_thread.lock_queue():
                sleep(.2)
            self.queue.append("tmtheme")
            self.update_thread.release_queue()

    def save(self, request, requester="Main Thread"):
        debug("%s requested save - %s" % (requester, request))
        if request == "tmtheme" or request == "all":
            try:
                with codec_open(self.tmtheme, "w", "utf-8") as f:
                    f.write((writePlistToString(self.scheme) + '\n').decode('utf8'))
            except:
                errormsg('Unexpected problem trying to write .tmTheme file!')

        if request == "json" or request == "all":
            try:
                with codec_open(self.json, "w", "utf-8") as f:
                    f.write((json.dumps(self.scheme, sort_keys=True, indent=4, separators=(',', ': ')) + '\n').decode('raw_unicode_escape'))
                self.updates_made = False
                if not self.live_save:
                    self.m_menuitem_save.Enable(False)
            except:
                errormsg('Unexpected problem trying to write .tmTheme.JSON file!')


    def rebuild_tables(self, cur_row, cur_col):
        cur_page = self.m_plist_notebook.GetSelection()

        self.m_global_settings.m_plist_grid.DeleteRows(0, self.m_global_settings.m_plist_grid.GetNumberRows())
        self.m_global_settings.read_plist(self.scheme)
        self.m_global_settings.go_cell(self.m_global_settings.m_plist_grid, 0, 0)

        self.m_style_settings.m_plist_grid.DeleteRows(0, self.m_style_settings.m_plist_grid.GetNumberRows())
        self.m_style_settings.read_plist(self.scheme)
        self.m_style_settings.go_cell(self.m_style_settings.m_plist_grid, 0, 0)

        if cur_page == 0:
            self.m_plist_notebook.ChangeSelection(cur_page)
            if cur_row is not None and cur_col is not None:
                self.m_global_settings.go_cell(self.m_global_settings.m_plist_grid, cur_row, cur_col, True)
        elif cur_page == 1:
            self.m_plist_notebook.ChangeSelection(cur_page)
            if cur_row is not None and cur_col is not None:
                self.m_style_settings.go_cell(self.m_style_settings.m_plist_grid, cur_row, cur_col, True)

    def set_style_object(self, obj):
        self.m_style_settings.set_object(obj)

    def set_global_object(self, key, value):
        self.m_global_settings.set_object(key, value)

    def focus_find(self, event):
        self.m_search_panel.SetFocus()
        event.Skip()

    def find(self):
        self.search_results = []
        pattern = self.m_search_panel.GetValue().lower()
        panel = self.m_style_settings if self.m_plist_notebook.GetSelection() else self.m_global_settings
        self.cur_search = panel
        grid = panel.m_plist_grid
        for r in range(0, grid.GetNumberRows()):
            for c in range(0, grid.GetNumberCols()):
                if pattern in grid.GetCellValue(r, c).lower():
                    self.search_results.append((r, c))

    def find_next(self, current=False):
        panel = self.m_style_settings if self.m_plist_notebook.GetSelection() else self.m_global_settings
        if self.cur_search is not panel:
            debug("Find: Panel switched.  Upate results.")
            self.find()
        grid = panel.m_plist_grid
        row = grid.GetGridCursorRow()
        col = grid.GetGridCursorCol()
        next = None
        for i in self.search_results:
            if current and row == i[0] and col == i[1]:
                next = i
                break
            elif row == i[0] and col < i[1]:
                next = i
                break
            elif row < i[0]:
                next = i
                break
        if next is None and len(self.search_results):
            next = self.search_results[0]
        if next is not None:
            grid.SetFocus()
            panel.go_cell(grid, next[0], next[1], True)

    def find_prev(self, current=False):
        panel = self.m_style_settings if self.m_plist_notebook.GetSelection() else self.m_global_settings
        if self.cur_search is not panel:
            debug("Find: Panel switched.  Upate results.")
            self.find()
        grid = panel.m_plist_grid
        row = grid.GetGridCursorRow()
        col = grid.GetGridCursorCol()
        prev = None
        for i in reversed(self.search_results):
            if current and row == i[0] and col == i[1]:
                prev = i
                break
            elif row == i[0] and col > i[1]:
                prev = i
                break
            elif row > i[0]:
                prev = i
                break
        if prev is None and len(self.search_results):
            prev = self.search_results[-1]
        if prev is not None:
            grid.SetFocus()
            panel.go_cell(grid, prev[0], prev[1], True)

    def file_close_cleanup(self):
        if self.live_save:
            self.update_thread.kill_thread()
            if self.live_save:
                while not self.update_thread.is_done():
                    sleep(0.5)
        if self.live_save and self.updates_made:
            self.save("json")
        elif not self.live_save and self.updates_made:
            if yesno(None, "You have unsaved changes.  Save?", "Color Scheme Editor"):
                self.save("all")

    def on_plist_name_blur(self, event):
        set_name = self.m_plist_name_textbox.GetValue()
        if set_name != self.last_plist_name:
            self.last_plist_name = set_name
            self.update_plist(JSON_NAME)
        event.Skip()

    def on_uuid_button_click(self, event):
        self.last_UUID = str(uuid.uuid4()).upper()
        self.m_plist_uuid_textbox.SetValue(self.last_UUID)
        self.update_plist(JSON_UUID)
        event.Skip()

    def on_uuid_blur(self, event):
        try:
            set_uuid = self.m_plist_uuid_textbox.GetValue()
            uuid.UUID(set_uuid)
            if set_uuid != self.last_UUID:
                self.last_UUID = set_uuid
                self.update_plist(JSON_UUID)
        except:
            self.on_uuid_button_click(event)
            errormsg('UUID is invalid! A new UUID has been generated.')
            debug("Bad UUID: %s!" % self.m_plist_uuid_textbox.GetValue())
        event.Skip()

    def on_plist_notebook_size(self, event):
        self.m_global_settings.resize_table()
        self.m_style_settings.resize_table()
        event.Skip()

    def on_open_new(self, event):
        self.file_close_cleanup()
        save_file = query_user_for_file(action="select")
        if save_file is not None:
            j_file, t_file, color_scheme = parse_file(save_file)
            if j_file is not None and t_file is not None:
                self.json = j_file
                self.tmtheme = t_file
                self.SetTitle("Color Scheme Editor - %s" % basename(t_file))
                self.scheme = color_scheme
                self.m_plist_name_textbox.SetValue(self.scheme["name"])
                self.m_plist_uuid_textbox.SetValue(self.scheme["uuid"])
                self.last_UUID = self.scheme["uuid"]
                self.last_plist_name = self.scheme["name"]
                self.rebuild_tables(None, None)

    def on_save(self, event):
        if not self.live_save:
            self.save("all")

    def on_save_as(self, event):
        save_file = query_user_for_file(action="new")
        if save_file is not None:
            j_file = None
            t_file = None
            is_json = file_path.lower().endswith("tmtheme.json")
            if is_json:
                j_file = file_path
                t_file = file_path[:-5]
            else:
                j_file = file_path + ".JSON"
                t_file = file_path
            self.json = j_file
            self.tmtheme = t_file
            self.SetTitle("Color Scheme Editor - %s" % basename(t_file))
            if self.live_save:
                while not self.update_thread.lock_queue():
                    sleep(.2)
                del self.queue[0:len(self.queue)]
                self.update_thread.release_queue()
            self.save("all")

    def on_about(self, event):
        infomsg("Color Scheme Editor: version %s" % __version__)
        event.Skip()

    def on_find(self, event):
        self.find()
        event.Skip()

    def on_find_finish(self, event):
        self.find_next(current=True)

    def on_next_find(self, event):
        self.find_next()

    def on_prev_find(self, event):
        self.find_prev()

    def on_shortcuts(self, event):
        if sys.platform == "darwin":
            msg = SHORTCUTS["osx"]
        elif sys.platform == "linux2":
            msg = SHORTCUTS["linux"]
        else:
            msg = SHORTCUTS["windows"]
        infomsg(msg,"Shortcuts")

    def on_debug_console(self, event):
        self.open_debug_console()

    def on_close(self, event):
        self.close_debug_console()
        self.file_close_cleanup()
        event.Skip()


#################################################
# Basic Dialogs
#################################################
def filepicker(parent, msg, wildcard, save=False):
    select = None
    style = wx.OPEN | wx.FILE_MUST_EXIST if not save else wx.SAVE | wx.OVERWRITE_PROMPT
    dialog = wx.FileDialog(
        parent, msg,
        "", wildcard=wildcard,
        style=style
    )
    if dialog.ShowModal() == wx.ID_OK:
        select = dialog.GetPath()
        dialog.Destroy()
    return select


def yesno(parent, question, caption = 'Yes or no?', yes="Okay", no="Cancel"):
    dlg = wx.MessageDialog(parent, question, caption, wx.YES_NO | wx.ICON_QUESTION)
    dlg.SetYesNoLabels(yes, no)
    result = dlg.ShowModal() == wx.ID_YES
    dlg.Destroy()
    return result


def infomsg(msg, title="INFO"):
    wx.MessageBox(msg, title, wx.OK | wx.ICON_INFORMATION)


def errormsg(msg, title="ERROR"):
    error(msg)
    wx.MessageBox(msg, title, wx.OK | wx.ICON_ERROR)


#################################################
# Theme Search methods/class support
#################################################
def strip_package_ext(pth):
    return pth[:-16] if pth.lower().endswith(".sublime-package") else pth


def sublime_format_path(pth):
    m = re.match(r"^([A-Za-z]{1}):(?:/|\\)(.*)", pth)
    if sys.platform.startswith('win') and m != None:
        pth = m.group(1) + "/" + m.group(2)
    return pth.replace("\\", "/")


def packages_path():
    return SUBLIME_PATHS[2] if SUBLIME_PATHS is not None else None


def installed_packages_path():
    return SUBLIME_PATHS[1] if SUBLIME_PATHS is not None else None


def default_packages_path():
    return SUBLIME_PATHS[0] if SUBLIME_PATHS is not None else None


class SublimeColorSchemeFiles(object):
    theme_files = {"pattern": "*.tmTheme", "regex": False}

    def find_files(self, files, pattern, settings, regex):
        for f in files:
            if regex:
                if re.match(pattern, f[0], re.IGNORECASE) != None:
                    settings.append([f[0].replace(self.packages, "").lstrip("\\").lstrip("/"), f[1]])
            else:
                if fnmatch(f[0], pattern):
                    settings.append([f[0].replace(self.packages, "").lstrip("\\").lstrip("/"), f[1]])

    def walk(self, settings, plugin, pattern, regex=False):
        for base, dirs, files in walk(plugin):
            files = [(join(base, f), "Packages") for f in files]
            self.find_files(files, pattern, settings, regex)

    def get_zip_packages(self, file_path, package_type):
        for item in listdir(file_path):
            if fnmatch(item, "*.sublime-package"):
                yield (join(file_path, item), package_type)

    def search_zipped_files(self, unpacked):
        installed = []
        default = []
        st_packages = [installed_packages_path(), default_packages_path()]
        unpacked_path = sublime_format_path(self.packages)
        default_path = sublime_format_path(st_packages[1])
        installed_path = sublime_format_path(st_packages[0])
        for p in self.get_zip_packages(st_packages[0], "Installed"):
            name = strip_package_ext(sublime_format_path(p[0]).replace(installed_path, ""))
            keep = True
            for i in unpacked:
                if name == sublime_format_path(i).replace(unpacked_path, ""):
                    keep = False
                    break
            if keep:
                installed.append(p)

        for p in self.get_zip_packages(st_packages[1], "Default"):
            name = strip_package_ext(sublime_format_path(p[0]).replace(default_path, ""))
            keep = True
            for i in installed:
                if name == strip_package_ext(sublime_format_path(i[0]).replace(installed_path, "")):
                    keep = False
                    break
            for i in unpacked:
                if name == strip_package_ext(sublime_format_path(i[0]).replace(unpacked_path, "")):
                    keep = False
                    break
            if keep:
                default.append(p)
        return sorted(default) + sorted(installed)

    def walk_zip(self, settings, plugin, pattern, regex):
        with zipfile.ZipFile(plugin[0], 'r') as z:
            zipped = [(join(strip_package_ext(basename(plugin[0])), normpath(fn)), plugin[1]) for fn in sorted(z.namelist())]
            self.find_files(zipped, pattern, settings, regex)

    def run(self, edit=True):
        self.edit = edit
        pattern = self.theme_files["pattern"]
        regex = bool(self.theme_files["regex"])
        self.packages = normpath(packages_path())
        settings = []
        plugins = sorted([join(self.packages, item) for item in listdir(self.packages) if isdir(join(self.packages, item))])
        for plugin in plugins:
            self.walk(settings, plugin, pattern.strip(), regex)

        self.zipped_idx = len(settings)

        zipped_plugins = self.search_zipped_files(plugins)
        for plugin in zipped_plugins:
            self.walk_zip(settings, plugin, pattern.strip(), regex)

        return settings


    # def open_zip_file(self, fn):
    #     file_name = None
    #     zip_package = None
    #     zip_file = None
    #     for zp in sublime_package_paths():
    #         items = fn.replace('\\', '/').split('/')
    #         zip_package = items.pop(0)
    #         zip_file = '/'.join(items)
    #         if exists(join(zp, zip_package)):
    #             zip_package = join(zp, zip_package)
    #             file_name = join(zp, fn)
    #             break

    #     if file_name is not None:
    #         with zipfile.ZipFile(zip_package, 'r') as z:
    #             text = z.read(z.getinfo(zip_file))
    #             view = self.window.open_file(file_name)
    #             WriteArchivedPackageContentCommand.bfr = text.decode('utf-8').replace('\r', '')
    #             sublime.set_timeout(lambda: view.run_command("write_archived_package_content"), 0)


#################################################
# Helper Functions
#################################################
def query_user_for_file(action):
    file_path = None
    select_file = action == "select"
    new_file = action == "new"
    select = False
    done = False
    if sys.platform == "darwin":
        wildcard = "(*.tmTheme;*.tmTheme.JSON)|*.tmTheme;*.JSON"
    else:
        wildcard = "(*.tmTheme;*.tmTheme.JSON)|*.tmTheme;*.tmTheme.JSON"
    if not select_file and not new_file:
        select = yesno(None, "Create a new theme or select an existing one?", "Color Scheme Editor", "Select", "New")
    elif select_file:
        select = True
    while not done:
        if select:
            result = filepicker(None, "Choose a theme file:", wildcard)
            if result is not None:
                debug(result)
                if not result.lower().endswith(".tmtheme.json") and not result.lower().endswith(".tmtheme"):
                    errormsg("File must be of type '.tmtheme' or '.tmtheme.json'")
                    debug("Select: Bad extension: %s" % result)
                    continue
                file_path = result
                debug("Select: File selected: %s" % file_path)
            done = True
        else:
            result = filepicker(None, "Theme file to save:", wildcard, True)
            if result is not None:
                if not result.lower().endswith(".tmtheme.json") and not result.lower().endswith(".tmtheme"):
                    errormsg("File must be of type '.tmtheme' or '.tmtheme.json'")
                    debug("New: Bad extension: %s" % result)
                    continue
                if result.lower().endswith("tmtheme.json"):
                    with codec_open(result, "w", "utf-8") as f:
                        f.write((json.dumps(default_new_theme, sort_keys=True, indent=4, separators=(',', ': ')) + '\n').decode('raw_unicode_escape'))
                else:
                    with codec_open(result, "w", "utf-8") as f:
                        f.write((writePlistToString(default_new_theme) + '\n').decode('utf8'))
                file_path = result
                debug("New: File selected: %s" % file_path)
            done = True
    return file_path

def parse_file(file_path):
    j_file = None
    t_file = None
    color_scheme = None
    is_json = file_path.lower().endswith("tmtheme.json")

    try:
        with open(file_path, "r") as f:
            color_scheme = json.loads(sanitize_json(f.read(), True)) if is_json else readPlist(f)
    except:
        errormsg('Unexpected problem trying to parse file!')

    if color_scheme is not None:
        if is_json:
            j_file = file_path
            t_file = file_path[:-5]

            if not exists(t_file):
                try:
                    with codec_open(t_file, "w", "utf-8") as f:
                        f.write((writePlistToString(color_scheme) + '\n').decode('utf8'))
                except:
                    debug("tmTheme file write error!")
        else:
            j_file = file_path + ".JSON"
            t_file = file_path

            if not exists(j_file):
                try:
                    with codec_open(j_file, "w", "utf-8") as f:
                        f.write((json.dumps(color_scheme, sort_keys=True, indent=4, separators=(',', ': ')) + '\n').decode('raw_unicode_escape'))
                except:
                    debug("JSON file write error!")

    return j_file, t_file, color_scheme


def parse_arguments(script):
    parser = argparse.ArgumentParser(prog='subclrschm', description='Sublime Color Scheme Editor - Edit Sublime Color Scheme')
    # Flag arguments
    parser.add_argument('--version', action='version', version=('%(prog)s ' + __version__))
    parser.add_argument('--debug', '-d', action='store_true', default=False, help=argparse.SUPPRESS)
    parser.add_argument('--log', '-l', nargs='?', default=script, help="Absolute path to directory to store log file")
    parser.add_argument('--live_save', '-L', action='store_true', default=False, help="Enable live save.")
    parser.add_argument('--sublime_paths', nargs=3, default=None, help="Sublime plugin paths (3): Default Installed User")
    # Mutually exclusinve flags
    group = parser.add_mutually_exclusive_group()
    group.add_argument('--select', '-s', action='store_true', default=False, help="Prompt for theme selection")
    group.add_argument('--new', '-n', action='store_true', default=False, help="Open prompting for new theme to create")
    #Positional
    parser.add_argument('file', nargs='?', default=None, help='Theme file')
    return parser.parse_args()


#################################################
# Main
#################################################
def main(script):
    cs = None
    j_file = None
    t_file = None
    args = parse_arguments(script)

    if exists(args.log):
        args.log = join(normpath(args.log), 'subclrschm.log')

    init_app_log(args.log)
    if args.debug:
        set_debug_mode(True)
    debug('Starting ColorSchemeEditor')
    debug('Arguments = %s' % str(args))

    if args.sublime_paths is not None:
        global SUBLIME_PATHS
        SUBLIME_PATHS = [args.sublime_paths[0], args.sublime_paths[1], args.sublime_paths[2]]
        try:
            debug(SublimeColorSchemeFiles().run())
        except Exception as e:
            error(e)

    app = CustomApp(redirect=args.debug)  #  , single_instance_name="subclrschm")

    if args.file is None:
        action = ""
        if args.select:
            action = "select"
        elif args.new:
            action = "new"
        args.file = query_user_for_file(action)

    if args.file is not None:
        j_file, t_file, cs = parse_file(args.file)

    if j_file is not None and t_file is not None:
        main_win = Editor(None, cs, j_file, t_file, live_save=args.live_save, debugging=args.debug)
        main_win.Show()
        wx.GetApp().MainLoop()
    return 0


if __name__ == "__main__":
    if sys.platform == "darwin" and len(sys.argv) > 1 and sys.argv[1].startswith("-psn"):
        script_path = join(dirname(abspath(sys.argv[0])), "..", "..", "..")
        del sys.argv[1]
    else:
        script_path = dirname(abspath(sys.argv[0]))

    sys.exit(main(script_path))
