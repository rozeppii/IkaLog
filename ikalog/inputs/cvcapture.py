#!/usr/bin/env python3
# -*- coding: utf-8 -*-
#
#  IkaLog
#  ======
#  Copyright (C) 2015 Takeshi HASEGAWA
#
#  Licensed under the Apache License, Version 2.0 (the "License");
#  you may not use this file except in compliance with the License.
#  You may obtain a copy of the License at
#
#      http://www.apache.org/licenses/LICENSE-2.0
#
#  Unless required by applicable law or agreed to in writing, software
#  distributed under the License is distributed on an "AS IS" BASIS,
#  WITHOUT WARRANTIES OR CONDITIONS OF ANY KIND, either express or implied.
#  See the License for the specific language governing permissions and
#  limitations under the License.
#
import os
import ctypes
import time
import threading

import cv2

from ikalog.utils import *


# Needed in GUI mode
try:
    import wx
except:
    pass


class InputSourceEnumerator(object):

    def enum_windows(self):
        numDevices = ctypes.c_int(0)
        r = self.dll.VI_Init()
        if (r != 0):
            return None

        r = self.dll.VI_GetDeviceNames(ctypes.pointer(numDevices))
        list = []
        for n in range(numDevices.value):
            friendly_name = self.dll.VI_GetDeviceName(n)
            list.append(friendly_name)

        self.dll.VI_Deinit()

        return list

    def enum_dummy(self):
        cameras = []
        for i in range(10):
            cameras.append('Input source %d' % (i + 1))

        return cameras

    def enumerate(self):
        if IkaUtils.isWindows():
            try:
                cameras = self.enum_windows()
                if len(cameras) > 1:
                    return cameras
            except:
                IkaUtils.dprint(
                    '%s: Failed to enumerate DirectShow devices' % self)

        return self.enum_dummy()

    def __init__(self):
        if IkaUtils.isWindows():
            videoinput_dll = os.path.join('lib', 'videoinput.dll')
            try:
                self.c_int_p = ctypes.POINTER(ctypes.c_int)

                ctypes.cdll.LoadLibrary(videoinput_dll)
                self.dll = ctypes.CDLL(videoinput_dll)

                self.dll.VI_Init.argtypes = []
                self.dll.VI_Init.restype = ctypes.c_int
                self.dll.VI_GetDeviceName.argtypes = [ctypes.c_int]
                self.dll.VI_GetDeviceName.restype = ctypes.c_char_p
                self.dll.VI_GetDeviceNames.argtypes = [self.c_int_p]
                self.dll.VI_GetDeviceNames.restype = ctypes.c_char_p
                self.dll.VI_GetDeviceName.argtypes = []
            except:
                IkaUtils.dprint(
                    "%s: Failed to initalize %s" % (self, videoinput_dll))


class CVCapture(object):
    cap = None
    out_width = 1280
    out_height = 720
    need_resize = False
    need_deinterlace = False
    realtime = True
    offset = (0, 0)

    _systime_launch = int(time.time() * 1000)

    # アマレコTV のキャプチャデバイス名
    DEV_AMAREC = "AmaRec Video Capture"

    source = 'amarec'
    source_device = None
    deinterlace = False
    File = ''

    lock = threading.Lock()

    def enumerate_input_sources(self):
        return InputSourceEnumerator().enumerate()

    def read(self):
        if self.cap is None:
            return None, None

        self.lock.acquire()
        try:
            ret, frame = self.cap.read()
        finally:
            self.lock.release()

        if not ret:
            return None, None

        if self.need_deinterlace:
            for y in range(frame.shape[0])[1::2]:
                frame[y, :] = frame[y - 1, :]

        if not (self.offset[0] == 0 and self.offset[1] == 0):
            ox = self.offset[0]
            oy = self.offset[1]

            sx1 = max(-ox, 0)
            sy1 = max(-oy, 0)

            dx1 = max(ox, 0)
            dy1 = max(oy, 0)

            w = min(self.out_width - dx1, self.out_width - sx1)
            h = min(self.out_height - dy1, self.out_height - sy1)

            frame[dy1:dy1 + h, dx1:dx1 + w] = frame[sy1:sy1 + h, sx1:sx1 + w]

        t = None
        if not self.realtime:
            try:
                t = self.cap.get(cv2.CAP_PROP_POS_MSEC)
            except:
                pass
            if t is None:
                IkaUtils.dprint('Cannot get video position...')
                self.realtime = True

        if self.realtime:
            t = int(time.time() * 1000) - self._systime_launch

        if t < self.last_t:
            IkaUtils.dprint(
                'FIXME: time position data rewinded. t=%x last_t=%x' % (t, self.last_t))
        self.last_t = t

        if self.need_resize:
            return cv2.resize(frame, (self.out_width, self.out_height)), t
        else:
            return frame, t

    def set_resolution(self, width, height):
        self.cap.set(3, width)
        self.cap.set(4, height)
        self.need_resize = (width != self.out_width) or (
            height != self.out_height)

    def init_capture(self, source, width=1280, height=720):
        self.lock.acquire()
        try:
            if not self.cap is None:
                self.cap.release()

            self.cap = cv2.VideoCapture(source)
            self.set_resolution(width, height)
            self.last_t = 0
        finally:
            self.lock.release()

    def is_windows(self):
        try:
            os.uname()
        except AttributeError:
            return True

        return False

    def start_camera(self, source_name):

        try:
            source = int(source_name)
        except:
            IkaUtils.dprint('%s: Looking up device name %s' %
                            (self, source_name))
            try:
                source_name = source_name.encode('utf-8')
            except:
                pass

            try:
                source = self.enumerate_input_sources().index(source_name)
            except:
                IkaUtils.dprint("%s: Input '%s' not found" %
                                (self, source_name))
                return False

        IkaUtils.dprint('%s: initalizing capture device %s' % (self, source))
        self.realtime = True
        self.from_file = False
        if self.is_windows():
            self.init_capture(700 + source)
        else:
            self.init_capture(0 + source)

    def start_recorded_file(self, file):
        IkaUtils.dprint(
            '%s: initalizing pre-recorded video file %s' % (self, file))
        self.realtime = False
        self.from_file = True
        self.init_capture(file)
        self.fps = self.cap.get(5)

    def restart_input(self):
        IkaUtils.dprint('RestartInput: source %s file %s device %s' %
                        (self.source, self.File, self.source_device))

        if self.source == 'camera':
            self.start_camera(self.source_device)

        elif self.source == 'file':
            self.start_recorded_file(self.File)
        else:
            # Use amarec if available
            self.source = 'amarec'

        if self.source == 'amarec':
            self.start_camera(self.DEV_AMAREC)

        success = True
        if self.cap is None:
            success = False

        if success:
            if not self.cap.isOpened():
                success = False

        return success

    def apply_ui(self):
        self.source = ''
        for control in [self.radioAmarecTV, self.radioCamera, self.radioFile]:
            if control.GetValue():
                self.source = {
                    self.radioAmarecTV: 'amarec',
                    self.radioCamera: 'camera',
                    self.radioFile: 'file',
                }[control]

        self.source_device = self.listCameras.GetItems(
        )[self.listCameras.GetSelection()]
        self.File = self.editFile.GetValue()
        self.deinterlace = self.checkDeinterlace.GetValue()

        # この関数は GUI 動作時にしか呼ばれない。カメラが開けなかった
        # 場合にメッセージを出す
        if not self.restart_input():
            r = wx.MessageDialog(None, u'キャプチャデバイスの初期化に失敗しました。設定を見直してください', 'Error',
                                 wx.OK | wx.ICON_ERROR).ShowModal()
            IkaUtils.dprint(
                "%s: failed to activate input source >>>>" % (self))
        else:
            IkaUtils.dprint("%s: activated new input source" % self)

    def refresh_ui(self):
        if self.source == 'amarec':
            self.radioAmarecTV.SetValue(True)

        if self.source == 'camera':
            self.radioCamera.SetValue(True)

        if self.source == 'file':
            self.radioFile.SetValue(True)

        try:
            dev = self.source_device
            index = self.listCameras.GetItems().index(dev)
            self.listCameras.SetSelection(index)
        except:
            IkaUtils.dprint('Current configured device is not in list')

        if not self.File is None:
            self.editFile.SetValue('')
        else:
            self.editFile.SetValue(self.File)

        self.checkDeinterlace.SetValue(self.deinterlace)

    def on_config_reset(self, context=None):
        # さすがにカメラはリセットしたくないな
        pass

    def on_config_load_from_context(self, context):
        self.on_config_reset(context)
        try:
            conf = context['config']['cvcapture']
        except:
            conf = {}

        self.source = ''
        try:
            if conf['Source'] in ['camera', 'file', u'camera', u'file']:
                self.source = conf['Source']
        except:
            pass

        if 'SourceDevice' in conf:
            try:
                self.source_device = conf['SourceDevice']
            except:
                # FIXME
                self.source_device = 0

        if 'File' in conf:
            self.File = conf['File']

        if 'Deinterlace' in conf:
            self.deinterlace = conf['Deinterlace']

        self.refresh_ui()
        return self.restart_input()

    def on_config_save_to_context(self, context):
        context['config']['cvcapture'] = {
            'Source': self.source,
            'File': self.File,
            'SourceDevice': self.source_device,
            'Deinterlace': self.deinterlace,
        }

    def on_config_apply(self, context):
        self.apply_ui()

    def on_reload_devices_button_click(self, event=None):
        cameras = self.enumerate_input_sources()
        self.listCameras.SetItems(cameras)
        try:
            index = self.enumerate_input_sources().index(self.source_device)
            self.listCameras.SetSelection(index)
        except:
            IkaUtils.dprint('Error: Device not found')

    def on_option_tab_create(self, notebook):
        self.panel = wx.Panel(notebook, wx.ID_ANY)
        self.page = notebook.InsertPage(0, self.panel, 'Input')

        cameras = self.enumerate_input_sources()

        self.layout = wx.BoxSizer(wx.VERTICAL)
        self.panel.SetSizer(self.layout)
        self.radioAmarecTV = wx.RadioButton(
            self.panel, wx.ID_ANY, u'Capture through AmarecTV')
        self.radioAmarecTV.SetValue(True)

        self.radioCamera = wx.RadioButton(
            self.panel, wx.ID_ANY, u'Realtime Capture from HDMI grabber')
        self.radioFile = wx.RadioButton(
            self.panel, wx.ID_ANY, u'Read from pre-recorded video file (for testing)')
        self.editFile = wx.TextCtrl(self.panel, wx.ID_ANY, u'hoge')
        self.listCameras = wx.ListBox(self.panel, wx.ID_ANY, choices=cameras)
        self.listCameras.SetSelection(0)
        self.buttonReloadDevices = wx.Button(
            self.panel, wx.ID_ANY, u'Reload Devices')
        self.checkDeinterlace = wx.CheckBox(
            self.panel, wx.ID_ANY, u'Enable Deinterlacing (experimental)')

        self.layout.Add(wx.StaticText(
            self.panel, wx.ID_ANY, u'Select Input source:'))
        self.layout.Add(self.radioAmarecTV)
        self.layout.Add(self.radioCamera)
        self.layout.Add(self.listCameras, flag=wx.EXPAND)
        self.layout.Add(self.buttonReloadDevices)
        self.layout.Add(self.radioFile)
        self.layout.Add(self.editFile, flag=wx.EXPAND)
        self.layout.Add(self.checkDeinterlace)
        self.layout.Add(wx.StaticText(self.panel, wx.ID_ANY, u'Video Offset'))

        self.buttonReloadDevices.Bind(
            wx.EVT_BUTTON, self.on_reload_devices_button_click)

if __name__ == "__main__":
    obj = CVCapture()

    list = InputSourceEnumerator().enumerate()
    for n in range(len(list)):
        print("%d: %s" % (n, list[n]))

    dev = input("Please input number (or name) of capture device: ")

    obj.start_camera(dev)

    k = 0
    while k != 27:
        frame, t = obj.read()
        cv2.imshow(obj.__class__.__name__, frame)
        k = cv2.waitKey(1)
