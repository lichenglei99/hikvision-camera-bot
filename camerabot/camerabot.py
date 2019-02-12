"""Camerabot Module"""

import logging
import os
import re
from datetime import datetime
from functools import wraps
from threading import Thread

from telegram import Bot
from telegram.utils.request import Request

from camerabot.errors import HomeCamError, UserAuthError


def authorization_check(func):
    """Decorator which checks that user is authorized to interact with bot."""

    @wraps(func)
    def wrapper(*args, **kwargs):
        bot, update = args
        try:
            if update.message.chat.id not in bot._user_ids:
                raise UserAuthError
            return func(*args, **kwargs)
        except UserAuthError:
            bot._log.error('User authorization error')
            bot._log.error(bot._get_user_info(update))
            bot._print_access_error(update)

    return wrapper


def camera_selection(func):
    """Decorator which checks which camera instance to use."""

    @wraps(func)
    def wrapper(*args, **kwargs):
        cambot, update = args
        cam_id = re.split(r'^.*(?=cam_)', update.message.text)[-1]
        cam = cambot._cam_instances[cam_id]['instance']
        args = args + (cam, cam_id)
        return func(*args, **kwargs)

    return wrapper


class CameraBot(Bot):
    """CameraBot class where main bot things are done."""

    def __init__(self, token, user_ids, cam_instances, stop_polling):
        super(CameraBot, self).__init__(token,
                                        request=(Request(con_pool_size=10)))
        self._log = logging.getLogger(self.__class__.__name__)
        self._cam_instances = cam_instances
        self._user_ids = user_ids
        self._stop_polling = stop_polling
        self._log.info('Initializing {0} bot'.format(self.first_name))

    def send_startup_message(self):
        """Send welcome message after bot launch."""
        self._log.info('Sending welcome message')

        for user_id in self._user_ids:
            self.send_message(user_id,
                              '{0} bot started, see /help for available commands'.format(
                                  self.first_name))

    def send_cam_photo(self, photo, update=None, caption=None, reply_text=None,
                       full_snapshot_name=None, full_pic=False,
                       from_watchdog=False):
        """Send received photo."""
        if from_watchdog:
            for uid in self._user_ids:
                filename = os.path.basename(photo.name)
                self.send_document(chat_id=uid, document=photo,
                                   caption=caption, filename=filename,
                                   timeout=300)
        else:
            update.message.reply_text(reply_text)
            if full_pic:
                update.message.reply_document(document=photo,
                                              filename=full_snapshot_name,
                                              caption=caption)
            else:
                update.message.reply_photo(photo=photo, caption=caption)

    @authorization_check
    @camera_selection
    def cmd_getpic(self, update, cam, cam_id):
        """Gets and sends resized snapshot from the camera."""
        self._log.info(
            'Resized cam snapshot from {0} requested'.format(cam.description))
        self._log.debug(self._get_user_info(update))

        try:
            photo, snapshot_timestamp = cam.take_snapshot(resize=True)
        except HomeCamError as err:
            update.message.reply_text(
                '{0}\nTry later or /list other cameras'.format(str(err)))
            return

        caption = 'Pic taken on {0:%a %b %-d %H:%M:%S %Y} (pic #{1})'.format(
            datetime.fromtimestamp(snapshot_timestamp), cam.snapshots_taken)
        reply_text = 'Sending pic from {0}...'.format(cam.description)
        self._log.info('Sending resized cam snapshot')
        self.send_cam_photo(photo=photo, update=update, caption=caption,
                            reply_text=reply_text)

        self._log.info('Resized snapshot sent')
        self._print_helper(update, cam_id)

    @authorization_check
    @camera_selection
    def cmd_getfullpic(self, update, cam, cam_id):
        """Gets and sends full snapshot from the camera."""
        self._log.info('Full cam snapshot requested')
        self._log.debug(self._get_user_info(update))

        try:
            photo, snapshot_timestamp = cam.take_snapshot(resize=False)
        except HomeCamError as err:
            update.message.reply_text(
                '{0}\nTry later or /list other cameras'.format(str(err)))
            return

        full_snapshot_name = 'Full_snapshot_{:%a_%b_%-d_%H.%M.%S_%Y}.jpg'.format(
            datetime.fromtimestamp(snapshot_timestamp))
        caption = 'Full pic taken on {0:%a %b %-d %H:%M:%S %Y} (pic #{1})'.format(
            datetime.fromtimestamp(snapshot_timestamp), cam.snapshots_taken)
        reply_text = 'Sending full pic from {0}...'.format(cam.description)
        self._log.info('Sending full snapshot')
        self.send_cam_photo(photo=photo, update=update, caption=caption,
                            reply_text=reply_text, \
                            full_snapshot_name=full_snapshot_name,
                            full_pic=True)
        self._log.info('Full cam snapshot {0} sent'.format(full_snapshot_name))
        self._print_helper(update, cam_id)

    @authorization_check
    def cmd_stop(self, update):
        """Terminates bot."""
        msg = 'Stopping {0} bot'.format(self.first_name)
        self._log.info(msg)
        self._log.debug(self._get_user_info(update))
        update.message.reply_text(msg)
        thread = Thread(target=self._stop_polling)
        thread.start()

    @authorization_check
    def cmd_list_cams(self, update):
        """Lists user's cameras."""
        self._log.info('Camera list has been requested')

        msg = ['<b>You have {0} cameras:</b>'.format(len(self._cam_instances))]

        for cam_id, cam_data in self._cam_instances.items():
            msg.append(
                '<b>Camera:</b> {0}\n<b>Description:</b> {1}\n<b>Commands:</b> {2}'.format(
                    cam_id, cam_data['instance'].description,
                    ', '.join(
                        '/{0}'.format(cmds) for cmds in cam_data['commands'])))

        update.message.reply_html('\n\n'.join(msg))

        self._log.info('Camera list has been sent')

    @authorization_check
    @camera_selection
    def cmd_motion_detection_off(self, update, cam, cam_id):
        """Disable camera's Motion Detection."""
        self._log.info('Disabling camera\'s Motion Detection has been '
                       'requested')
        self._log.debug(self._get_user_info(update))
        try:
            cam.motion_detection_switch(enable=False)
            msg = 'Motion Detection successfully disabled.'
            update.message.reply_text(msg)
            self._log.info(msg)
            self._print_helper(update, cam_id)
        except HomeCamError as err:
            update.message.reply_text(str(err))
            return

    @authorization_check
    @camera_selection
    def cmd_motion_detection_on(self, update, cam, cam_id):
        """Enable camera's Motion Detection."""
        self._log.info('Enabling camera\'s Motion Detection has been '
                       'requested')
        self._log.debug(self._get_user_info(update))
        try:
            cam.motion_detection_switch(enable=True)
            msg = 'Motion Detection successfully enabled.'
            update.message.reply_text(msg)
            self._log.info(msg)
            self._print_helper(update, cam_id)
        except HomeCamError as err:
            update.message.reply_text(str(err))
            return

    def cmd_help(self, update, append=False, requested=True, cam_id=None):
        """Sends help message to telegram chat."""
        if requested:
            self._log.info('Help message has been requested')
            self._log.debug(self._get_user_info(update))
            update.message.reply_text(
                'Use /list command to list available cameras and commands')
        elif append:
            update.message.reply_text(
                'Available commands\n{0} or /list available cameras'.format(
                    '\n'.join('/{0}'.format(x) for x in
                              self._cam_instances[cam_id]['commands'])))

        self._log.info('Help message has been sent')

    def error_handler(self, update, error):
        """Handles known telegram bot api errors."""
        self._log.error('Got error: {0}'.format(error))

    def _print_helper(self, update, cam_id):
        """Sends help message to telegram chat after sending picture."""
        self.cmd_help(update, append=True, requested=False, cam_id=cam_id)

    def _print_access_error(self, update):
        """Sends authorization error to telegram chat."""
        update.message.reply_text('Not authorized')

    def _get_user_info(self, update):
        """Returns user information who interacts with bot."""
        return 'Request from user_id: {0}, username: {1}, first_name: {2}, last_name: {3}'.format(
            update.message.chat.id,
            update.message.chat.username,
            update.message.chat.first_name,
            update.message.chat.last_name)