#!/usr/bin/env python
import os
import re
import tempfile
import lxml.html
import lxml.html.soupparser
import mechanize

encoders = {
    '320': {
        'format' : 'MP3',
        'bitrate' : '320'
        },
    'V0': {
        'format' : 'MP3',
        'bitrate' : 'V0 (VBR)'
        },
    'V2': {
        'format' : 'MP3', 
        'bitrate' : 'V2 (VBR)'
        },
    'Q8': {
        'format' : 'Ogg Vorbis',
        'bitrate' : 'q8.x (VBR)'
        },
    'AAC': {
        'format' : 'AAC',
        'bitrate': '320'
        },
    'FLAC': {
        'format': 'FLAC',
        'bitrate': 'Lossless'
        }
}

class WhatBrowser(mechanize.Browser):
    def __init__(self, username, password):
        mechanize.Browser.__init__(self)

        self.set_handle_robots(False)
        self.open('http://what.cd/login.php')

        self.select_form(nr=0)
        self['username'] = username
        self['password'] = password
        self.submit()

    def goto(self, url, refresh=False):
        if self.geturl() != url or refresh:
            return self.open(url)
        else:
            return self._response

    def get_release(self, release_url_or_id):
        releaseid = re.search('[0-9]+$', release_url_or_id).group(0)
        return Release(self, releaseid)

    def get_torrent(self, torrent_url_or_id):
        torrentid = re.search('[0-9]+$', torrent_url_or_id).group(0)
        return Torrent(self, torrentid)

    def transcode_candidates(self):
        self.goto('http://what.cd/better.php?method=snatch')
        doc = parse_html(self._response.read())

        for release_url in doc.cssselect('.thin a'):
            if release_url.get('title') == 'View Torrent':
                url = release_url.get('href')
                yield self.get_release(url)

class Release:
    def __init__(self, browser, releaseid):
        self.browser = browser
        self.id = releaseid
        self.url = 'http://what.cd/torrents.php?id=%s' % self.id
        self.upload_url = 'http://what.cd/upload.php?groupid=%s' % self.id
        self.retrieve_info()
        self.torrents = self.get_torrents()
        self.media = [t.media for t in self.torrents if t.codec == 'FLAC'][0]

    def retrieve_info(self):
        response = self.browser.goto(self.url).read()
        doc = parse_html(response)
        for header in doc.cssselect('div#content div.thin h2'):
            artist, info = header.text_content().split(' - ')
            self.artist = artist
            result = re.search('([^\[]+)\s\[([^\]]+)\]\s\[([^\]]+)\]', info)
            self.title = result.group(1)
            self.year = result.group(2)
            self.release_type = result.group(3)

        try:
            self.album_info = doc.cssselect('html body#torrents div#wrapper div#content div.thin div.main_column div.box div.body')[0].text_content()
        except IndexError:
            self.album_info = None

    def get_torrents(self):
        try:
            return self.torrents
        except:
            pass

        torrents = []

        response = self.browser.goto(self.url)
        doc = parse_html(response.read())

        for torrent_group in doc.cssselect('.group_torrent'):
            try:
                torrentid = torrent_group.get('id').replace('torrent', '')
                torrents.append(Torrent(self.browser, torrentid))
            except:
                continue
        
        return torrents

    def formats_needed(self):
        current_formats = [t.codec for t in self.get_torrents()]
        formats_needed = [codec for codec in encoders.keys() if codec not in current_formats]
        return formats_needed

    def add_format(self, transcode_dir, codec):
        torrent = transcode.make_torrent(transcode_dir)

        self.browser.goto(self.upload_url)
        # select the last form on the page
        self.browser.select_form(nr=len(list(browser.forms()))-1) 

        # add the torrent
        self.browser.find_control('file_input').add_file(open(torrent), 'text/plain', os.path.basename(torrent))

        # specify format
        self.browser.find_control('format').set('1', encoders[codec]['format'])

        # specify bitrate
        self.browser.find_control('bitrate').set('1', encoders[codec]['bitrate'])

        # specify media
        self.browser.find_control('media').set('1', self.media)

        # specify release description
        self.browser['release_desc'] = 'Created with [url=http://github.com/zacharydenton/whatbetter/]whatbetter[/url].'

        # submit the form
        response = self.browser.submit()
        return response

class Torrent:
    def __init__(self, browser, torrentid):
        self.browser = browser
        self.id = torrentid
        self.url = 'http://what.cd/torrents.php?torrentid=%s' % self.id
        self.retrieve_info()

    def retrieve_info(self):
        response = self.browser.goto(self.url).read()
        doc = parse_html(response)
        for torrent_group in doc.cssselect('tr#torrent%s' % self.id):
            for torrent_info in torrent_group.cssselect('td a'):
                if torrent_info.text_content() in ['RP', 'PL']:
                    continue
                elif torrent_info.text_content() == 'DL':
                    self.download_link = torrent_info.get('href')
                else:
                    info = torrent_info.text_content()[1:].strip() # trim leading char
                    result = info.split(' / ')
                    self.format = result[0].strip()
                    self.bitrate = result[1].strip()
                    self.media = result[2].strip()
                    self.codec = get_codec(self.format, self.bitrate)
                    try:
                        scene = result[3]
                        self.scene = True
                    except IndexError:
                        self.scene = False

        for filelist in doc.cssselect('#files_%s' % self.id):
            print filelist.text_content()
            self.files = []
            for i, row in enumerate(filelist.cssselect('tr')):
                if i == 0:
                    self.folder = row.cssselect('td div')[0].text_content()
                    continue
                self.files.append(row.cssselect('td')[0].text_content())
                
    def download(self, output_dir=None):
        if output_dir is None:
            output_dir = os.getcwd()
        path = os.path.join(output_dir, self.get_filename())
        filename, headers = self.browser.urlretrieve(self.url, path)
        return filename

def parse_html(html):
    try:
        return lxml.html.fromstring(html)
    except:
        return lxml.html.soupparser.fromstring(html)

def get_codec(fmt, bitrate):
    for codec, properties in encoders.items():
        if properties['format'] == fmt and properties['bitrate'] == bitrate:
            return codec
    return None
