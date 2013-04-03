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
from os.path import exists, normpath, join, dirname
from os import remove
import _lib.simplelog as Log

__version__ = "0.0.2"

BG_COLOR = None
FG_COLOR = None


#################################################
# Debug and Logging
#################################################
log = None


def log_gui(msg):
    log.info(msg, "%(message)s")


class CustomLog(wx.PyOnDemandOutputWindow):
    def write(self, text):
        if self.frame is None:
            if not wx.Thread_IsMain():
                wx.CallAfter(log_gui, text)
                # wx.CallAfter(self.CreateOutputWindow, text)
            else:
                log_gui(text)
                # self.CreateOutputWindow(text)
        else:
            if not wx.Thread_IsMain():
                wx.CallAfter(log_gui, text)
                # wx.CallAfter(self.text.AppendText, text)
            else:
                log_gui(text)
                # self.text.AppendText(text)


class CustomApp(wx.App):
    def __init__(self, *args, **kwargs):
        self.outputWindowClass = CustomLog
        super(CustomApp, self).__init__(*args, **kwargs)


#################################################
# Grid Helper Class
#################################################
class GridHelper(object):
    cell_select_semiphore = False
    range_semiphore = False
    current_row = None
    current_col = None

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

    def grid_select_cell(self, grid, event):
        if not self.cell_select_semiphore and event.Selecting():
            self.cell_select_semiphore = True
            self.current_row = event.GetRow()
            self.current_col = event.GetCol()
            self.go_cell(grid, self.current_row, self.current_col)
            self.cell_select_semiphore = False

    def grid_range_select(self, grid, event):
        r1 = event.GetTopRow()
        r2 = event.GetBottomRow()
        c1 = event.GetLeftCol()
        c2 = event.GetRightCol()
        rows = len(grid.GetSelectedRows())
        if self.cell_select_semiphore:
            pass
        elif not self.range_semiphore and (r1 != r2 or c1 != c2):
            if event.Selecting():
                self.range_semiphore = True
                grid.ClearSelection()
                if self.current_row is not None and self.current_col:
                    self.go_cell(grid, self.current_row, self.current_col)
                self.range_semiphore = False
            elif rows == 0:
                if self.current_row is not None:
                    self.range_semiphore = True
                    self.go_cell(grid, self.current_row, self.current_col)
                    self.range_semiphore = False
        else:
            event.Skip()

    def mouse_motion(self, event):
        if event.Dragging():       # mouse being dragged?
            pass                   # eat the event
        else:
            event.Skip()           # no dragging, pass on to the window

    def grid_key_down(self, grid, event):
        is_style = isinstance(grid.GetParent(), StyleSettings)
        if (
            not event.HasModifiers() and
            not event.MetaDown() and
            not event.ShiftDown()
        ):
            if event.GetKeyCode() == wx.WXK_DELETE:
                self.delete_row(grid, event)
                return
            elif event.GetKeyCode() == wx.WXK_RETURN:
                if isinstance(grid.GetParent(), StyleSettings):
                    grid.GetParent().edit_style(grid)
                else:
                    grid.GetParent().edit_global(grid)
                return
        elif event.AltDown():
            if event.GetKeyCode() == wx.WXK_UP:
                if is_style:
                    self.up_button_click(grid, event)
                return
            elif event.GetKeyCode() == wx.WXK_DOWN:
                if is_style:
                    self.down_button_click(grid, event)
                return
            elif event.GetKeyCode() == wx.WXK_LEFT:
                return
            elif event.GetKeyCode() == wx.WXK_RIGHT:
                return
            elif event.GetKeyCode() == 0x49:
                self.insert_row_before(grid, event)
                # if event.ShiftDown():
                #     self.insert_row_before(grid, event)
                # else:
                #     self.insert_row_after(grid, event)
                return
        if event.ControlDown() or event.ShiftDown():
            if event.GetKeyCode() == wx.WXK_UP:
                return
            elif event.GetKeyCode() == wx.WXK_DOWN:
                return
            elif event.GetKeyCode() == wx.WXK_LEFT:
                return
            elif event.GetKeyCode() == wx.WXK_RIGHT:
                return
        event.Skip()

    def up_button_click( self, grid, event ):
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
            grid.GetParent().rebuild()
            # grid.GoToCell(row - 1, col)
        grid.SetFocus()
        event.Skip()

    def down_button_click( self, grid, event ):
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
            grid.GetParent().rebuild()
            # grid.GoToCell(row + 1, col)
        grid.SetFocus()
        event.Skip()

    def edit_style(self, grid):
        row = grid.GetGridCursorRow()
        ColorEditor(
            wx.GetApp().TopWindow,
            {
                "name": grid.GetCellValue(row, 0),
                "scope": grid.GetCellValue(row, 4),
                "settings": {
                    "foreground": grid.GetCellValue(row, 1),
                    "background": grid.GetCellValue(row, 2),
                    "fontStyle": grid.GetCellValue(row, 3)
                }
            }
        ).Show()

    def edit_global(self, grid):
        row = grid.GetGridCursorRow()
        GlobalEditor(
            wx.GetApp().TopWindow,
            grid.GetCellValue(row, 0),
            grid.GetCellValue(row, 1)
        ).Show()

    def insert_row_before(self, grid, event):
        num = grid.GetNumberRows()
        row = grid.GetGridCursorRow()
        if num > 0:
            grid.InsertRows(row, 1, True)
        else:
            grid.AppendRows(1)
            row = 0
        if isinstance(grid.GetParent(), StyleSettings):
            text = ["New Item", "#FFFFFF", "#000000", "", "comment"]
            [grid.SetCellValue(row, x, text[x]) for x in range(0, 5)]
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
            self.go_cell(grid, row, 0)
            grid.GetParent().rebuild()
            ColorEditor(
                wx.GetApp().TopWindow,
                obj
            ).Show()
        else:
            text = ["new_item", "nothing"]
            [grid.SetCellValue(row, x, text[x]) for x in range(0, 2)]
            grid.GetParent().update_row(row, text[0], text[1])
            self.go_cell(grid, row, 0)
            grid.GetParent().rebuild()
            GlobalEditor(
                wx.GetApp().TopWindow,
                text[0],
                text[1]
            ).Show()

    def insert_row_after(self, grid, event):
        row = grid.GetGridCursorRow()
        pass

    def delete_row(self, grid, event):
        row = grid.GetGridCursorRow()
        grid.DeleteRows(row, 1)
        grid.GetParent().rebuild()


#################################################
# Grid Display Panels
#################################################
class StyleSettings(editor.StyleSettingsPanel, GridHelper):
    def __init__(self, parent, scheme, rebuild):
        super(StyleSettings, self).__init__(parent)
        self.parent = parent
        wx.EVT_MOTION(self.m_plist_grid.GetGridWindow(), self.on_mouse_motion)
        self.m_plist_grid.SetDefaultCellBackgroundColour(self.GetBackgroundColour())
        self.read_plist(scheme)
        self.rebuild = rebuild

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

        if "fontStyle" in settings:
            font_style = []
            for x in settings["fontStyle"].split(" "):
                if x in ["bold", "italic", "underline"]:
                    font_style.append(x)

            self.m_plist_grid.SetCellValue(count, 3, " ".join(font_style))
            fs = self.m_plist_grid.GetCellFont(count, 0)
            update_font = False
            if "bold" in font_style:
                fs.SetWeight(wx.BOLD)
                update_font = True
            if "italic" in font_style:
                fs.SetStyle(wx.ITALIC)
                update_font = True
            if "underline" in font_style:
                fs.SetUnderlined(True)
                update_font = True
            if update_font:
                self.m_plist_grid.SetCellFont(count, 0, fs)
                self.m_plist_grid.SetCellFont(count, 1, fs)
                self.m_plist_grid.SetCellFont(count, 2, fs)
                self.m_plist_grid.SetCellFont(count, 3, fs)
                self.m_plist_grid.SetCellFont(count, 4, fs)

    def set_object(self, obj):
        row = self.m_plist_grid.GetGridCursorRow()
        col = self.m_plist_grid.GetGridCursorCol()
        self.update_row(row, obj)
        self.rebuild()
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

    def on_grid_select_cell(self, event):
        self.grid_select_cell(self.m_plist_grid, event)

    def on_grid_range_select(self, event):
        self.grid_range_select(self.m_plist_grid, event)

    def on_mouse_motion(self, event):
        self.mouse_motion(event)

    def on_grid_key_down(self, event):
        self.grid_key_down(self.m_plist_grid, event)

    def on_edit_cell(self, event):
        self.edit_style(self.m_plist_grid)


class GlobalSettings(editor.GlobalSettingsPanel, GridHelper):
    def __init__(self, parent, scheme, rebuild):
        super(GlobalSettings, self).__init__(parent)
        self.parent = parent
        wx.EVT_MOTION(self.m_plist_grid.GetGridWindow(), self.on_mouse_motion)
        self.m_plist_grid.SetDefaultCellBackgroundColour(self.GetBackgroundColour())
        self.read_plist(scheme)
        self.rebuild = rebuild

    def read_plist(self, scheme):
        foreground = RGBA(scheme["settings"][0]["settings"].get("foreground", "#000000"))
        background = RGBA(scheme["settings"][0]["settings"].get("background", "#FFFFFF"))
        global BG_COLOR
        BG_COLOR = background
        global FG_COLOR
        FG_COLOR = foreground
        count = 0

        self.m_plist_grid.BeginBatch()
        for k in sorted(scheme["settings"][0]["settings"].iterkeys()):
            v = scheme["settings"][0]["settings"][k]
            self.m_plist_grid.AppendRows(1)
            self.update_row(count, k, v)
            count += 1
        nb_size = self.parent.GetSize()
        total_size = 0
        for x in range(0, 2):
            self.m_plist_grid.AutoSizeColumn(x)
            total_size += self.m_plist_grid.GetColSize(x)
        delta = nb_size[0] - 20 - total_size
        if delta > 0:
            self.m_plist_grid.SetColSize(1, self.m_plist_grid.GetColSize(1) + delta)
        self.m_plist_grid.EndBatch()
        self.go_cell(self.m_plist_grid, 0, 0)

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
        self.rebuild()
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

    def on_grid_select_cell( self, event ):
        self.grid_select_cell(self.m_plist_grid, event)

    def on_grid_range_select( self, event ):
        self.grid_range_select(self.m_plist_grid, event)

    def on_mouse_motion(self, event):
        self.mouse_motion(event)

    def on_grid_key_down( self, event ):
        self.grid_key_down(self.m_plist_grid, event)

    def on_edit_cell(self, event):
        self.edit_global(self.m_plist_grid)


#################################################
# Settings Dialogs
#################################################
class GlobalEditor(editor.GlobalSetting):
    def __init__(self, parent, name, value):
        super(GlobalEditor, self).__init__(parent)
        self.Parent.Disable()
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
        self.apply_settings = True
        self.Close()

    def on_set_color_close(self, event):
        if self.apply_settings:
            self.obj_key = self.m_name_textbox.GetValue()
            self.obj_val = self.m_value_textbox.GetValue()

            self.Parent.set_global_object(self.obj_key, self.obj_val)

        self.Parent.Enable()
        event.Skip()


class ColorEditor(editor.ColorSetting):
    def __init__(self, parent, obj):  # name, foreground, background, fontstyle, scope):
        super(ColorEditor, self).__init__(parent)
        self.Parent.Disable()
        self.Fit()
        size = self.GetSize()
        self.SetMinSize(size)
        size.Set(-1, size[1])
        self.SetMaxSize(size)
        self.foreground_save = ""
        self.background_save = ""
        self.apply_settings = False
        self.color_obj = obj

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

            self.Parent.set_style_object(self.color_obj)
        self.Parent.Enable()

        event.Skip()


#################################################
# Main Dialog
#################################################
class Editor(editor.EditorFrame):
    def __init__(self, parent, scheme, j_file, t_file):
        super(Editor, self).__init__(parent)
        self.SetTitle("Color Scheme Editor %s" % __version__)
        self.last_UUID = None
        self.last_plist_name = None
        self.scheme = scheme
        self.json = j_file
        self.tmtheme = t_file
        self.m_global_settings = GlobalSettings(self.m_plist_notebook, scheme, self.rebuild_plist)
        self.m_style_settings = StyleSettings(self.m_plist_notebook, scheme, self.rebuild_plist)

        self.m_plist_name_textbox.SetValue(scheme["name"])
        self.m_plist_uuid_textbox.SetValue(scheme["uuid"])
        self.last_UUID = scheme["uuid"]
        self.last_plist_name = scheme["name"]

        self.m_plist_notebook.InsertPage(0, self.m_global_settings, "Global Settings", True)
        self.m_plist_notebook.InsertPage(1, self.m_style_settings, "Scope Settings", False)

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

        try:
            with codec_open(self.json, "w", "utf-8") as f:
                f.write((json.dumps(self.scheme, sort_keys=True, indent=4, separators=(',', ': ')) + '\n').decode('raw_unicode_escape'))
        except:
            wx.MessageBox('Unexpected problem trying to write .tmTheme.JSON file!', 'ERROR', wx.OK | wx.ICON_ERROR)

        try:
            with codec_open(self.tmtheme, "w", "utf-8") as f:
                f.write((writePlistToString(self.scheme) + '\n').decode('utf8'))
        except:
            wx.MessageBox('Unexpected problem trying to write .tmTheme file!', 'ERROR', wx.OK | wx.ICON_ERROR)

    def rebuild_tables(self, cur_row, cur_col):
        self.rebuild_plist()
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

    def update_plist(self):
        cur_page = self.m_plist_notebook.GetSelection()
        grid = self.m_global_settings.m_plist_grid if cur_page == 0 else self.m_style_settings.m_plist_grid
        row, col = grid.GetGridCursorRow(), grid.GetGridCursorCol()
        self.rebuild_plist(row, col)

    def on_plist_name_blur(self, event):
        set_name = self.m_plist_name_textbox.GetValue()
        if set_name != self.last_plist_name:
            self.last_plist_name = set_name
            self.update_plist()

    def on_uuid_button_click(self, event):
        self.last_UUID = str(uuid.uuid4()).upper()
        self.m_plist_uuid_textbox.SetValue(self.last_UUID)
        self.update_plist()
        event.Skip()

    def on_uuid_blur(self, event):
        try:
            set_uuid = self.m_plist_uuid_textbox.GetValue()
            uuid.UUID(set_uuid)
            if set_uuid != self.last_UUID:
                self.last_UUID = set_uuid
                self.update_plist()
        except:
            self.on_uuid_button_click(event)
            wx.MessageBox('UUID is invalid! A new UUID has been generated.', 'ERROR', wx.OK | wx.ICON_ERROR)

    def set_style_object(self, obj):
        self.m_style_settings.set_object(obj)

    def set_global_object(self, key, value):
        self.m_global_settings.set_object(key, value)

    def on_plist_notebook_size(self, event):
        nb_size = self.m_plist_notebook.GetSize()
        grid = self.m_global_settings.m_plist_grid
        grid.BeginBatch()
        total_size = 0
        grid.AutoSizeColumn(1)
        for x in range(0, 2):
            total_size += grid.GetColSize(x)
        delta = nb_size[0] - 20 - total_size
        if delta > 0:
            grid.SetColSize(1, grid.GetColSize(1) + delta)
        grid.EndBatch()
        grid = self.m_style_settings.m_plist_grid
        grid.BeginBatch()
        total_size = 0
        grid.AutoSizeColumn(4)
        for x in range(0, 5):
            total_size += grid.GetColSize(x)
        delta = nb_size[0] - 20 - total_size
        if delta > 0:
            grid.SetColSize(4, grid.GetColSize(4) + delta)
        grid.EndBatch()
        event.Skip()


def main(script):
    global log
    cs = None
    j_file = None
    t_file = None
    parser = argparse.ArgumentParser(prog='subclrschm', description='Sublime Color Scheme Editor - Edit Sublime Color Scheme')
    # Flag arguments
    parser.add_argument('--version', action='version', version=('%(prog)s ' + __version__))
    parser.add_argument('--debug', '-d', action='store_true', default=False, help=argparse.SUPPRESS)
    parser.add_argument('--log', '-l', nargs='?', default=script, help="Absolute path to directory to store log file")
    parser.add_argument('--json', '-j', action='store_true', default=False, help='json tmTheme file')
    parser.add_argument('file', nargs='?', default=None, help='Theme file')
    args = parser.parse_args()

    if exists(args.log):
        args.log = join(normpath(args.log), 'subclrschm.log')
    level = Log.DEBUG if args.debug else Log.INFO

    log = Log.Log(format='%(message)s', filename=args.log, level=level, filemode="w")
    log.debug('Starting ColorSchemeEditor')
    log.debug('Arguments = %s' % str(args))

    app = CustomApp(redirect=True)

    if args.file is None:
        log.debug("Show file picker.")
        wildcard = "*.tmTheme.JSON" if args.json else "*.tmTheme"
        dialog = wx.FileDialog(
            None, "Choose a theme file:",
            "", wildcard=wildcard
        )
        if dialog.ShowModal() == wx.ID_OK:
            args.file = dialog.GetPath()
            log.debug("File selectd: %s" % args.file)
            dialog.Destroy()

    if args.file is not None:
        try:
            with open(args.file, "r") as f:
                cs = json.loads(sanitize_json(f.read(), True)) if args.json else readPlist(f)
        except:
            wx.MessageBox('Unexpected problem trying to parse file!', 'ERROR', wx.OK | wx.ICON_ERROR)

        if args.json:
            j_file = args.file
            t_file = args.file[:-5]
        else:
            j_file = args.file + ".JSON"
            t_file = args.file

    if j_file is not None and t_file is not None:
        main_win = Editor(None, cs, j_file, t_file)
        main_win.Show()
        app.MainLoop()

    log.debug("Exiting")
    return 0

if __name__ == "__main__":
    if sys.platform == "darwin" and len(sys.argv) > 1 and sys.argv[1].startswith("-psn"):
        script_path = join(dirname(sys.argv[0]), "..", "..", "..")
        del sys.argv[1]
    else:
        script_path = dirname(sys.argv[0])

    sys.exit(main(script_path))
