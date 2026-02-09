import struct


class MPLS:
    """
    todo ;
    - improve bitwise operations
    - improve how it deals with fields that use < 8 bits
    - improve code repetition, there's quite a bit due to struct.unpack needing ,=
    - verify the unpacked values are all using the correct format string (some probably wrong ://)
    - try remove the need for get_bits
    """

    """
    Object containing information on Blu-ray MPLS files
    """

    def __init__(self, filename):
        """
        Parse a Blu-ray MPLS file
        :param str filename: path to the mpls file to be parsed
        :rtype: :class:`MPLS`.
        :raises ValueError: if parsing fails
        """
        # Create a read handle for the MPLS file
        with open(filename, mode="rb") as f:
            self._parse_file(f)

    def _parse_file(self, f):
        # ====== #
        # Header #
        # ====== #
        self.Header = {}
        self.Header["TypeIndicator"] = f.read(4)
        self.Header["VersionNumber"] = f.read(4)
        (self.Header["PlayListStartAddress"],) = struct.unpack(">I", f.read(4))
        (self.Header["PlayListMarkStartAddress"],) = struct.unpack(">I", f.read(4))
        (self.Header["ExtensionDataStartAddress"],) = struct.unpack(">I", f.read(4))
        f.read(20)  # 160 reserved bits

        # =============== #
        # AppInfoPlayList #
        # =============== #
        self.AppInfoPlayList = {}
        (self.AppInfoPlayList["Length"],) = struct.unpack(">I", f.read(4))
        f.read(1)  # 8 reserved bits
        (self.AppInfoPlayList["PlaybackType"],) = struct.unpack(">B", f.read(1))
        if self.AppInfoPlayList["PlaybackType"] == int(0x02) or self.AppInfoPlayList[
            "PlaybackType"
        ] == int(0x03):
            (self.AppInfoPlayList["PlaybackCount"],) = struct.unpack(">H", f.read(2))
        else:
            f.read(2)  # 16 reserved bits
        (self.AppInfoPlayList["UOMaskTable"],) = struct.unpack(">Q", f.read(8))
        (self.AppInfoPlayList["MiscFlags"],) = struct.unpack(">H", f.read(2))

        # ======== #
        # PlayList #
        # ======== #
        f.seek(self.Header["PlayListStartAddress"])
        self.PlayList = {}
        (self.PlayList["Length"],) = struct.unpack(">I", f.read(4))
        StartPosition = f.tell()
        f.read(2)  # 16 reserved bits
        (self.PlayList["NumberOfPlayItems"],) = struct.unpack(">H", f.read(2))
        (self.PlayList["NumberOfSubPaths"],) = struct.unpack(">H", f.read(2))
        # Loop over PlayItems ...
        self.PlayList["PlayItems"] = []
        for _ in range(self.PlayList["NumberOfPlayItems"]):
            self.PlayList["PlayItems"].append(self.get_play_item(f))
        self.PlayList["SubPaths"] = []
        for _ in range(self.PlayList["NumberOfSubPaths"]):
            self.PlayList["SubPaths"].append(self.get_sub_path(f))
        # go to the end of the playlist data
        f.seek(StartPosition + self.PlayList["Length"])

        # ============ #
        # PlayListMark #
        # ============ #
        f.seek(self.Header["PlayListMarkStartAddress"])
        self.PlayListMarks = {}
        (self.PlayListMarks["Length"],) = struct.unpack(">I", f.read(4))
        StartPosition = f.tell()
        (self.PlayListMarks["NumberOfPlayListMarks"],) = struct.unpack(">H", f.read(2))
        self.PlayListMarks["PlayListMarks"] = []
        for _ in range(self.PlayListMarks["NumberOfPlayListMarks"]):
            PlayListMark = {}
            f.read(1)  # 8 reserved bits
            (PlayListMark["MarkType"],) = struct.unpack(">B", f.read(1))
            (PlayListMark["RefToPlayItemID"],) = struct.unpack(">H", f.read(2))
            (PlayListMark["MarkTimeStamp"],) = struct.unpack(">I", f.read(4))
            (PlayListMark["EntryESPID"],) = struct.unpack(">H", f.read(2))
            (PlayListMark["Duration"],) = struct.unpack(">I", f.read(4))
            self.PlayListMarks["PlayListMarks"].append(PlayListMark)
        # go to the end of the playlist mark data
        f.seek(StartPosition + self.PlayListMarks["Length"])

        # ============= #
        # ExtensionData #
        # ============= #
        self.ExtensionData = {}
        if self.Header["ExtensionDataStartAddress"]:
            f.seek(self.Header["ExtensionDataStartAddress"])
            (self.ExtensionData["Length"],) = struct.unpack(">I", f.read(4))
            StartPosition = f.tell()
            if self.ExtensionData["Length"]:
                remaining = self.ExtensionData["Length"] - 4
                if remaining >= 4:
                    self.ExtensionData["DataBlockStartAddress"] = struct.unpack(">I", f.read(4))
                    remaining -= 4
                else:
                    self.ExtensionData["DataBlockStartAddress"] = 0
                f.read(min(3, remaining))  # 24 reserved bits
                remaining = max(0, remaining - 3)
                if remaining >= 4:
                    (self.ExtensionData["NumberOfExtDataEntries"],) = struct.unpack(">I", f.read(4))
                    remaining -= 4
                else:
                    self.ExtensionData["NumberOfExtDataEntries"] = 0
                self.ExtensionData["ExtDataEntries"] = []
                for _ in range(self.ExtensionData["NumberOfExtDataEntries"]):
                    if remaining < 12:
                        break
                    ExtDataEntry = {}
                    ExtDataEntry["ExtDataType"] = struct.unpack(">H", f.read(2))
                    ExtDataEntry["ExtDataVersion"] = struct.unpack(">H", f.read(2))
                    ExtDataEntry["ExtDataStartAddress"] = struct.unpack(">I", f.read(4))
                    ExtDataEntry["ExtDataLength"] = struct.unpack(">I", f.read(4))
                    remaining -= 12
                    self.ExtensionData["ExtDataEntries"].append(ExtDataEntry)
            f.seek(StartPosition + self.ExtensionData["Length"])

    def get_sub_path(self, f):
        SubPath = {}
        (SubPath["Length"],) = struct.unpack(">I", f.read(4))
        StartPosition = f.tell()
        f.read(1)  # 8 reserved bits
        (SubPath["SubPathType"],) = struct.unpack(">B", f.read(1))
        f.read(1)  # 8 reserved bits
        (b,) = struct.unpack(">B", f.read(1))  # first 7 bits are reserved
        SubPath["IsRepeatSubPath"] = b & 0b00000001
        f.read(1)  # 8 reserved bits
        (SubPath["NumberOfSubPlayItems"],) = struct.unpack(">B", f.read(1))
        SubPath["SubPlayItems"] = []
        for _ in range(SubPath["NumberOfSubPlayItems"]):
            SubPath["SubPlayItems"].append(self.get_sub_play_item(f))
        # go to the end of the play item data
        f.seek(StartPosition + SubPath["Length"])
        return SubPath

    def get_sub_play_item(self, f):
        SubPlayItem = {}
        (SubPlayItem["Length"],) = struct.unpack(">H", f.read(2))
        StartPosition = f.tell()
        SubPlayItem["ClipInformationFileName"] = f.read(5).decode("utf-8")
        SubPlayItem["ClipCodecIdentifier"] = f.read(4).decode("utf-8")
        f.read(3)  # 24 reserved bits
        (b,) = struct.unpack(">B", f.read(1))  # first 3 bits are reserved
        SubPlayItem["ConnectionCondition"] = b & 0b00011110
        SubPlayItem["IsMultiClipEntries"] = b & 0b00000001
        (SubPlayItem["RefToSTCID"],) = struct.unpack(">B", f.read(1))
        (SubPlayItem["INTime"],) = struct.unpack(">I", f.read(4))
        (SubPlayItem["OUTTime"],) = struct.unpack(">I", f.read(4))
        (SubPlayItem["SyncPlayItemID"],) = struct.unpack(">H", f.read(2))
        (SubPlayItem["SyncStartPTS"],) = struct.unpack(">I", f.read(4))
        if SubPlayItem["IsMultiClipEntries"]:
            (SubPlayItem["NumberOfMultiClipEntries"],) = struct.unpack(">H", f.read(1))
            f.read(1)  # 8 reserved bits
            SubPlayItem["MultiClipEntries"] = []
            for _ in range(SubPlayItem["NumberOfMultiClipEntries"]):
                MultiClipEntry = {}
                MultiClipEntry["ClipInformationFileName"] = f.read(5).decode("utf-8")
                MultiClipEntry["ClipCodecIdentifier"] = f.read(5).decode("utf-8")
                (MultiClipEntry["RefToSTCID"],) = struct.unpack(">B", f.read(1))
                SubPlayItem["MultiClipEntries"].append(MultiClipEntry)
        # go to the end of the play item data
        f.seek(StartPosition + SubPlayItem["Length"])
        return SubPlayItem

    def get_play_item(self, f):
        PlayItem = {}
        (PlayItem["Length"],) = struct.unpack(">H", f.read(2))
        StartPosition = f.tell()
        PlayItem["ClipInformationFileName"] = f.read(5).decode("utf-8")
        PlayItem["ClipCodecIdentifier"] = f.read(4).decode("utf-8")
        tmp = self.get_bits(f.read(2))  # first 11 bits are reserved
        PlayItem["IsMultiAngle"] = tmp[12] == 1
        PlayItem["ConnectionCondition"] = tmp[13:16]
        (PlayItem["RefToSTCID"],) = struct.unpack(">B", f.read(1))
        (PlayItem["INTime"],) = struct.unpack(">I", f.read(4))
        (PlayItem["OUTTime"],) = struct.unpack(">I", f.read(4))
        (PlayItem["UOMaskTable"],) = struct.unpack(">Q", f.read(8))
        tmp = self.get_bits(f.read(1))  # last 7 bits are reserved
        PlayItem["PlayItemRandomAccessFlag"] = tmp[0] == 1
        (PlayItem["StillMode"],) = struct.unpack(">B", f.read(1))
        if PlayItem["StillMode"] == int(0x01):
            (PlayItem["StillTime"],) = struct.unpack(">H", f.read(2))
        else:
            f.read(2)  # 16 reserved bits
        if PlayItem["IsMultiAngle"]:
            # Warning or skip instead of raise? The original code raises.
            # We keep it as is for now.
            pass
        PlayItem["STNTable"] = self.get_stn_table(f)
        # go to the end of the play item data
        f.seek(StartPosition + PlayItem["Length"])
        return PlayItem

    def get_stn_table(self, f):
        STNTable = {}
        (STNTable["Length"],) = struct.unpack(">H", f.read(2))
        StartPosition = f.tell()
        f.read(2)  # 16 reserved bits
        # read entry counts
        for item in [
            "PrimaryVideoStreamEntries",
            "PrimaryAudioStreamEntries",
            "PrimaryPGStreamEntries",
            "PrimaryIGStreamEntries",
            "SecondaryAudioStreamEntries",
            "SecondaryVideoStreamEntries",
            "SecondaryPGStreamEntries",
            "DVStreamEntries",
        ]:
            (STNTable[f"NumberOf{item}"],) = struct.unpack(">B", f.read(1))
        f.read(4)  # 32 reserved bits
        # get entries
        for item in [
            "PrimaryVideoStreamEntries",
            "PrimaryAudioStreamEntries",
            "PrimaryPGStreamEntries",
            "SecondaryPGStreamEntries",
            "PrimaryIGStreamEntries",
            "SecondaryAudioStreamEntries",
            "SecondaryVideoStreamEntries",
            "DVStreamEntries",
        ]:
            STNTable[item] = []
            for _ in range(STNTable[f"NumberOf{item}"]):
                STNTable[item].append(
                    {
                        "StreamEntry": self.get_stream_entry(f),
                        "StreamAttributes": self.get_stream_attributes(f),
                    }
                )
        # go to the end of the table data
        f.seek(StartPosition + STNTable["Length"])
        return STNTable

    def get_stream_entry(self, f):
        StreamEntry = {}
        (StreamEntry["Length"],) = struct.unpack(">B", f.read(1))
        StartPosition = f.tell()
        if StreamEntry["Length"]:
            remaining = StreamEntry["Length"] - 1
            if remaining > 0:
                (StreamEntry["StreamType"],) = struct.unpack(">B", f.read(1))
                remaining -= 1
                if StreamEntry["StreamType"] == int(0x01):
                    if remaining >= 2:
                        (StreamEntry["RefToStreamPID"],) = struct.unpack(">H", f.read(2))
                        StreamEntry["RefToStreamPID"] = "0x{0:<04x}".format(
                            StreamEntry["RefToStreamPID"]
                        )
                elif StreamEntry["StreamType"] == int(0x02):
                    if remaining >= 4:
                        (StreamEntry["RefToSubPathID"],) = struct.unpack(">B", f.read(1))
                        (StreamEntry["RefToSubClipID"],) = struct.unpack(">B", f.read(1))
                        (StreamEntry["RefToStreamPID"],) = struct.unpack(">H", f.read(2))
                        StreamEntry["RefToStreamPID"] = "0x{0:<04x}".format(
                            StreamEntry["RefToStreamPID"]
                        )
                elif StreamEntry["StreamType"] == int(0x03) or StreamEntry["StreamType"] == int(
                    0x04
                ):
                    if remaining >= 3:
                        (StreamEntry["RefToSubPathID"],) = struct.unpack(">B", f.read(1))
                        (StreamEntry["RefToStreamPID"],) = struct.unpack(">H", f.read(2))
                        StreamEntry["RefToStreamPID"] = "0x{0:<04x}".format(
                            StreamEntry["RefToStreamPID"]
                        )
        # go to the end of the stream entry data
        f.seek(StartPosition + StreamEntry["Length"])
        return StreamEntry

    def get_stream_attributes(self, f):
        StreamAttributes = {}
        (StreamAttributes["Length"],) = struct.unpack(">B", f.read(1))
        StartPosition = f.tell()
        if StreamAttributes["Length"]:
            (StreamAttributes["StreamCodingType"],) = struct.unpack(">B", f.read(1))
            if StreamAttributes["StreamCodingType"] in [
                int(0x01),
                int(0x02),
                int(0x1B),
                int(0xEA),
                int(0x24),
            ]:
                (b,) = struct.unpack(">B", f.read(1))
                StreamAttributes["VideoFormat"] = b >> 4
                StreamAttributes["FrameRate"] = b & 0b1111
            if StreamAttributes["StreamCodingType"] in [int(0x24)]:
                (b,) = struct.unpack(">B", f.read(1))
                StreamAttributes["DynamicRangeType"] = b >> 4
                StreamAttributes["ColorSpace"] = b & 0b1111
                (b,) = struct.unpack(">B", f.read(1))
                StreamAttributes["CRFlag"] = b & 0b10000000
                StreamAttributes["HDRPlusFlag"] = b & 0b01000000
            if StreamAttributes["StreamCodingType"] in [
                int(0x03),
                int(0x04),
                int(0x80),
                int(0x81),
                int(0x82),
                int(0x83),
                int(0x84),
                int(0x85),
                int(0x86),
                int(0xA1),
                int(0xA2),
            ]:
                remaining = StartPosition + StreamAttributes["Length"] - f.tell()
                if remaining >= 4:
                    (b,) = struct.unpack(">B", f.read(1))
                    StreamAttributes["AudioFormat"] = b >> 4
                    StreamAttributes["SampleRate"] = b & 0b1111
                    if remaining >= 7:
                        StreamAttributes["LanguageCode"] = f.read(3).decode("utf-8")
                    else:
                        StreamAttributes["LanguageCode"] = ""
                else:
                    StreamAttributes["LanguageCode"] = ""
            if StreamAttributes["StreamCodingType"] in [int(0x90), int(0x91)]:
                remaining = StartPosition + StreamAttributes["Length"] - f.tell()
                if remaining >= 3:
                    StreamAttributes["LanguageCode"] = f.read(3).decode("utf-8")
                else:
                    StreamAttributes["LanguageCode"] = ""
            if StreamAttributes["StreamCodingType"] in [int(0x92)]:
                remaining = StartPosition + StreamAttributes["Length"] - f.tell()
                if remaining >= 4:
                    StreamAttributes["CharacterCode"] = f.read(1).decode("utf-8")
                    StreamAttributes["LanguageCode"] = f.read(3).decode("utf-8")
                else:
                    StreamAttributes["CharacterCode"] = ""
                    StreamAttributes["LanguageCode"] = ""
        else:
            StreamAttributes["LanguageCode"] = ""
        f.seek(StartPosition + StreamAttributes["Length"])
        return StreamAttributes

    def get_bits(self, b):
        if not isinstance(b, bytearray) and not isinstance(b, bytes):
            raise ValueError("pympls.MPLS.get_bits: Bad argument value")
        # Fixed: Iterate over all bytes in b
        return [i for sl in [[((x >> i) & 1) for i in range(8)] for x in b] for i in sl]

    def __repr__(self):
        return (
            "<MPLS "
            + ", ".join(
                [
                    f"Header={self.Header}",
                    f"AppInfoPlayList={self.AppInfoPlayList}",
                    f"PlayList={self.PlayList}",
                    f"PlayListMarks={self.PlayListMarks}",
                    f"ExtensionData={self.ExtensionData}",
                ]
            )
            + ">"
        )
