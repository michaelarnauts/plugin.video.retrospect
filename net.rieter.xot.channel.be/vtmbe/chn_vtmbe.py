import datetime
import time

import chn_class
from logger import Logger
from mediaitem import MediaItem
from vault import Vault
from urihandler import UriHandler
from helpers.jsonhelper import JsonHelper
from addonsettings import AddonSettings
from helpers.htmlentityhelper import HtmlEntityHelper
from streams.m3u8 import M3u8
from regexer import Regexer
from xbmcwrapper import XbmcWrapper
from helpers.languagehelper import LanguageHelper


class Channel(chn_class.Channel):
    """
    main class from which all channels inherit
    """

    def __init__(self, channelInfo):
        """Initialisation of the class.

        Arguments:
        channelInfo: ChannelInfo - The channel info object to base this channel on.

        All class variables should be instantiated here and this method should not
        be overridden by any derived classes.

        """

        chn_class.Channel.__init__(self, channelInfo)

        # ============== Actual channel setup STARTS here and should be overwritten from derived classes ===============
        self.noImage = "vtmbeimage.jpg"

        # setup the urls
        # self.mainListUri = "http://vtm.be/feed/programs?format=json&type=all&only_with_video=true"
        self.mainListUri = "http://vtm.be/video/?f[0]=sm_field_video_origin_cms_longform%3AVolledige%20afleveringen"
        self.baseUrl = "http://vtm.be"

        # setup the main parsing data
        self._AddDataParser("http://vtm.be/feed/programs?format=json&type=all&only_with_video=true",
                            name="JSON Feed Show Parser",
                            json=True, preprocessor=self.AddLiveChannel,
                            creator=self.CreateEpisodeItem, parser=("response", "items"))

        self._AddDataParser("http://vtm.be/feed/articles?program=", json=True,
                            name="JSON Video Parser",
                            creator=self.CreateVideoItem, parser=("response", "items"))

        htmlEpisodeRegex = '<a[^>]+href="(?<url>[^"]+sm_field_program_active[^"]+)"[^>]*>(?<title>[^(<]+)'
        htmlEpisodeRegex = Regexer.FromExpresso(htmlEpisodeRegex)
        self._AddDataParser(
            "http://vtm.be/video/?f[0]=sm_field_video_origin_cms_longform%3AVolledige%20afleveringen",
            name="HTML Page Show Parser",
            preprocessor=self.AddLiveChannel,
            parser=htmlEpisodeRegex,
            creator=self.CreateEpisodeItemHtml)

        htmlVideoRegex = '<img[^>]+class="media-object"[^>]+src="(?<thumburl>[^"]+)[^>]*>[\w\W]{0,1000}?<a[^>]+href="/(?<url>[^"]+)"[^>]*>(?<title>[^<]+)'
        htmlVideoRegex = Regexer.FromExpresso(htmlVideoRegex)
        self._AddDataParser(
            "http://vtm.be/video/?f[0]=sm_field_video_origin_cms_longform%3AVolledige%20afleveringen&",
            name="HTML Page Video Parser",
            parser=htmlVideoRegex, creator=self.CreateVideoItemHtml,
            updater=self.UpdateVideoItem)

        self._AddDataParser("#livestream", name="Live Stream Updater", requiresLogon=True,
                            updater=self.UpdateLiveStream)

        # ===============================================================================================================
        # non standard items
        self.__signatureSettings = "channel_7F92EAEE-6066-4ED5-911A-2C3DCF964D19_signature"
        self.__signature = None
        self.__signatureTimeStamp = None
        self.__userId = None

        # ===============================================================================================================
        # Test cases:

        # ====================================== Actual channel setup STOPS here =======================================
        return

    def LogOn(self):
        signatureSetting = AddonSettings.GetSetting(self.__signatureSettings)
        if signatureSetting:
            signatureTimestamp, signature, userId = signatureSetting.split("|", 2)
            if time.time() < int(signatureTimestamp) + 1 * 60:
                Logger.Info("Found valid signature for userId %s", userId)
                self.__signature = signature
                self.__userId = userId
                self.__signatureTimeStamp = signatureTimestamp
                return True

        Logger.Info("Logging onto VTM.be")
        v = Vault()
        password = v.GetChannelSetting("7F92EAEE-6066-4ED5-911A-2C3DCF964D19", "password")
        username = self._GetSetting("username")
        if not username or not password:
            XbmcWrapper.ShowDialog(
                title=None,
                lines=LanguageHelper.GetLocalizedString(LanguageHelper.MissingCredentials),
                # notificationType=XbmcWrapper.Error,
                # displayTime=5000
            )
            return False
        # username = HtmlEntityHelper.UrlEncode(username)
        # password = HtmlEntityHelper.UrlEncode(password)

        Logger.Debug("Using: %s / %s", username, password)
        url = "https://accounts.eu1.gigya.com/accounts.login" \
              "?APIKey=3_HZ0FtkMW_gOyKlqQzW5_0FHRC7Nd5XpXJZcDdXY4pk5eES2ZWmejRW5egwVm4ug-" \
              "&sdk=js_6.1" \
              "&format=json" \
              "&loginID=%s" \
              "&password=%s" % (username, password)

        logonData = UriHandler.Open(url, proxy=self.proxy)
        logonJson = JsonHelper(logonData)
        resultCode = logonJson.GetValue("statusCode")
        if resultCode != 200:
            Logger.Error("Error loging in: %s - %s", logonJson.GetValue("errorMessage"),
                         logonJson.GetValue("errorDetails"))
            return False

        self.__signature = logonJson.GetValue("UIDSignature")
        self.__userId = logonJson.GetValue("UID")
        self.__signatureTimeStamp = logonJson.GetValue("signatureTimestamp")
        AddonSettings.SetSetting(self.__signatureSettings, "%s|%s|%s" % (
            self.__signatureTimeStamp,
            self.__signature,
            self.__userId))
        return True

    def CreateEpisodeItem(self, resultSet):
        """Creates a new MediaItem for an episode

       Arguments:
       resultSet : list[string] - the resultSet of the self.episodeItemRegex

       Returns:
       A new MediaItem of type 'folder'

       This method creates a new MediaItem from the Regular Expression or Json
       results <resultSet>. The method should be implemented by derived classes
       and are specific to the channel.

       """

        Logger.Trace(resultSet)

        title = resultSet['title']
        archived = resultSet['archived']
        if archived:
            Logger.Warning("Found archived item: %s", title)
            return None

        programId = resultSet['id']
        url = "http://vtm.be/feed/articles" \
              "?program=%s" \
              "&fields=text,video&type=all" \
              "&sort=mostRecent" \
              "&&count=100" \
              "&filterExcluded=true" % (programId, )
        item = MediaItem(title, url)
        item.fanart = self.fanart
        item.thumb = self.noImage
        item.description = resultSet.get('body', None)

        if 'images' in resultSet and 'image' in resultSet['images']:
            item.thumb = resultSet['images']['image'].get('full', self.noImage)
        return item

    def CreateVideoItem(self, resultSet):
        """Creates a MediaItem of type 'video' using the resultSet from the regex.

        Arguments:
        resultSet : tuple (string) - the resultSet of the self.videoItemRegex

        Returns:
        A new MediaItem of type 'video' or 'audio' (despite the method's name)

        This method creates a new MediaItem from the Regular Expression or Json
        results <resultSet>. The method should be implemented by derived classes
        and are specific to the channel.

        If the item is completely processed an no further data needs to be fetched
        the self.complete property should be set to True. If not set to True, the
        self.UpdateVideoItem method is called if the item is focussed or selected
        for playback.

        """

        Logger.Trace(resultSet)

        title = resultSet['title']
        item = MediaItem(title, "", type="video")
        item.description = resultSet.get('text')

        if 'image' in resultSet:
            item.thumb = resultSet['image'].get("full", None)

        created = Channel.GetDateFromPosix(resultSet['created']['timestamp'])
        item.SetDate(created.year, created.month, created.day, created.hour, created.minute,
                     created.second)

        if 'video' not in resultSet:
            Logger.Warning("Found item without video: %s", item)
            return None

        item.AppendSingleStream(resultSet['video']['url']['default'], 0)
        item.complete = True
        return item

    def CreateEpisodeItemHtml(self, resultSet):
        """Creates a new MediaItem for an episode

       Arguments:
       resultSet : list[string] - the resultSet of the self.episodeItemRegex

       Returns:
       A new MediaItem of type 'folder'

       This method creates a new MediaItem from the Regular Expression or Json
       results <resultSet>. The method should be implemented by derived classes
       and are specific to the channel.

       """

        Logger.Trace(resultSet)

        title = resultSet['title']
        url = HtmlEntityHelper.StripAmp(resultSet['url'])
        # We need to convert the URL
        # http://vtm.be/video/?f[0]=sm_field_video_origin_cms_longform%3AVolledige%20afleveringen&amp;f[1]=sm_field_program_active%3AAlloo%20bij%20de%20Wegpolitie
        # http://vtm.be/video/?amp%3Bf[1]=sm_field_program_active%3AAlloo%20bij%20de%20Wegpolitie&f[0]=sm_field_video_origin_cms_longform%3AVolledige%20afleveringen&f[1]=sm_field_program_active%3AAlloo%20bij%20de%20Wegpolitie

        item = MediaItem(title, url)
        item.fanart = self.fanart
        item.thumb = self.noImage
        return item

    def CreateVideoItemHtml(self, resultSet):
        """Creates a MediaItem of type 'video' using the resultSet from the regex.

        Arguments:
        resultSet : tuple (string) - the resultSet of the self.videoItemRegex

        Returns:
        A new MediaItem of type 'video' or 'audio' (despite the method's name)

        This method creates a new MediaItem from the Regular Expression or Json
        results <resultSet>. The method should be implemented by derived classes
        and are specific to the channel.

        If the item is completely processed an no further data needs to be fetched
        the self.complete property should be set to True. If not set to True, the
        self.UpdateVideoItem method is called if the item is focussed or selected
        for playback.

        """

        Logger.Trace(resultSet)

        title = resultSet['title']
        url = "%s/%s" % (self.baseUrl, resultSet["url"])
        item = MediaItem(title, url, type="video")
        item.thumb = resultSet['thumburl']
        item.complete = False
        return item

    def UpdateVideoItem(self, item):
        """Updates an existing MediaItem with more data.

        Arguments:
        item : MediaItem - the MediaItem that needs to be updated

        Returns:
        The original item with more data added to it's properties.

        Used to update none complete MediaItems (self.complete = False). This
        could include opening the item's URL to fetch more data and then process that
        data or retrieve it's real media-URL.

        The method should at least:
        * cache the thumbnail to disk (use self.noImage if no thumb is available).
        * set at least one MediaItemPart with a single MediaStream.
        * set self.complete = True.

        if the returned item does not have a MediaItemPart then the self.complete flag
        will automatically be set back to False.

        """

        Logger.Debug('Starting UpdateVideoItem for %s (%s)', item.name, self.channelName)

        if not self.loggedOn:
            self.loggedOn = self.LogOn()
        if not self.loggedOn:
            Logger.Warning("Cannot log on")
            return None

        data = UriHandler.Open(item.url, proxy=self.proxy)
        dataRegex = '.vmmaplayer\(([^<]+)\);\W+</script>'
        videoData = Regexer.DoRegex(dataRegex, data)[0]
        videoJson = JsonHelper("[%s]" % (videoData, ), logger=Logger.Instance())
        videoData = videoJson.GetValue(1)

        mediaUrl = "http://vod.medialaan.io/api/1.0/item/" \
                   "%s" \
                   "/video?app_id=vtm_watch&user_network=vtm-sso" \
                   "&UID=%s" \
                   "&UIDSignature=%s" \
                   "&signatureTimestamp=%s" % (
                       videoData["id"],
                       self.__userId,
                       HtmlEntityHelper.UrlEncode(self.__signature),
                       self.__signatureTimeStamp
                   )

        data = UriHandler.Open(mediaUrl, proxy=self.proxy)
        jsonData = JsonHelper(data)
        m3u8Url = jsonData.GetValue("response", "uri")
        # m3u8Url = jsonData.GetValue("response", "hls-drm-uri")  # not supported by Kodi
        part = item.CreateNewEmptyMediaPart()
        for s, b in M3u8.GetStreamsFromM3u8(m3u8Url, self.proxy):
            item.complete = True
            # s = self.GetVerifiableVideoUrl(s)
            part.AppendMediaStream(s, b)

        # duration is not calculated correctly
        duration = videoData["duration"]
        item.SetInfoLabel("Duration", duration)

        # http://vod.medialaan.io/api/1.0/item/
        # vtm_20161124_VM0677613_vtmwatch
        # /video?app_id=vtm_watch&user_network=vtm-sso
        # &UID=897b786c46e3462eac81549453680c0d
        # &UIDSignature=Hf4TrZ7TFwH5cjeJ8pqVwjFp25I%3D
        # &signatureTimestamp=1481494782

        return item

    def AddLiveChannel(self, data):
        Logger.Info("Performing Pre-Processing")
        username = self._GetSetting("username")
        if not username:
            return data, []

        items = []

        item = MediaItem("Live VTM", "#livestream")
        item.type = "video"
        item.isLive = True
        item.fanart = self.fanart
        item.thumb = self.noImage
        items.append(item)

        Logger.Debug("Pre-Processing finished")
        return data, items

    def UpdateLiveStream(self, item):
        Logger.Debug("Updating Live stream")
        # no cache
        # http://stream-live.medialaan.io/stream-live/v1/channels/vtm/episodes/current/video?access_token=xY7XaPCwD%2BdO3T%2F83b1KSSen2Vk7wOKs3aaWR585Olqwk0DGR4qISGXHm%2BztUY9odESYeXGWgV%2FQ30Hb%2BmLBnPFCsGu%2FYYDcJLirGEqzeeJNrK%2BviJNzgbLFY2x3iN73s58%2BB3rdEApGIqnBegVxCe55P0RFeVhcXbRuzYXXik2UErI84sXcPvASzZPfoef28fClf7xo%2BM0OrrPQFRq23w%3D%3D&_=1480883641044
        # let's request a token
        token = self.__GetToken()
        url = "http://stream-live.medialaan.io/stream-live/v1/channels/vtm/episodes/current/video?access_token=%s&_=%s" % (
            HtmlEntityHelper.UrlEncode(token),
            int(time.time())  # Could be a random int
        )
        data = UriHandler.Open(url, proxy=self.proxy, noCache=True)
        jsonData = JsonHelper(data)
        hls = jsonData.GetValue("response", "url", "hls")
        if not hls:
            return item

        part = item.CreateNewEmptyMediaPart()
        for s, b in M3u8.GetStreamsFromM3u8(hls, self.proxy):
            item.complete = True
            # s = self.GetVerifiableVideoUrl(s)
            part.AppendMediaStream(s, b)
        return item

    @staticmethod
    def GetDateFromPosix(posix, tz=None):
        # type: (float) -> datetime.datetime
        """ Creates a datetime from a Posix Time stamp

        @param posix:   the posix time stamp integer
        @return:        a valid datetime.datetime object.
        """

        return datetime.datetime.fromtimestamp(posix, tz)

    def __GetToken(self):
        """ Requests a playback token """
        if not self.loggedOn:
            self.loggedOn = self.LogOn()
        if not self.loggedOn:
            Logger.Warning("Cannot log on")
            return None

        # https://user.medialaan.io/user/v1/gigya/request_token?uid=897b786c46e3462eac81549453680c0d&signature=Ak10FWFpuF2cSXfmGnNIBsJV4ss%3D&timestamp=1481233821&apikey=vtm-b7sJGrKwMJj0VhdZvqLDFvgkJF5NLjNY&database=vtm-sso
        apiKey = "vtm-b7sJGrKwMJj0VhdZvqLDFvgkJF5NLjNY"
        url = "https://user.medialaan.io/user/v1/gigya/request_token?uid=%s&signature=%s&timestamp=%s&apikey=%s&database=vtm-sso" % (
            self.__userId,
            HtmlEntityHelper.UrlEncode(self.__signature),
            self.__signatureTimeStamp,
            HtmlEntityHelper.UrlEncode(apiKey))
        data = UriHandler.Open(url, proxy=self.proxy, noCache=True)
        jsonData = JsonHelper(data)
        return jsonData.GetValue("response")