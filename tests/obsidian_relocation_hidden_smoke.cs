using System;
using System.Diagnostics;
using System.IO;

internal static class ObsidianHiddenLauncherSmoke
{
    private const int SyntheticChildExitCode = 7;

    private static int Main(string[] args)
    {
        if (args.Length == 1 && args[0] == "--synthetic-child-exit-7")
            return SyntheticChildExitCode;

        if (args.Length != 2 || args[0] != "--verify-launcher")
            return 90;

        try
        {
            if (ReadSubsystem(args[1]) != 2)
                return 93;

            string self = Process.GetCurrentProcess().MainModule.FileName;
            int actual = HiddenProcess.Run(self, "--synthetic-child-exit-7",
                                           Path.GetDirectoryName(self));
            if (actual != SyntheticChildExitCode)
                return 91;

            Console.WriteLine("GUI subsystem verified: 2");
            Console.WriteLine("synthetic exit code propagated: 7");
            return 0;
        }
        catch
        {
            return 92;
        }
    }

    private static int ReadSubsystem(string path)
    {
        byte[] bytes = File.ReadAllBytes(path);
        if (bytes.Length < 0x40 || bytes[0] != (byte)'M' || bytes[1] != (byte)'Z')
            throw new InvalidDataException("DOS header");

        int pe = BitConverter.ToInt32(bytes, 0x3c);
        if (pe < 0 || pe > bytes.Length - 24 - 70)
            throw new InvalidDataException("PE header bounds");
        if (bytes[pe] != (byte)'P' || bytes[pe + 1] != (byte)'E' ||
            bytes[pe + 2] != 0 || bytes[pe + 3] != 0)
            throw new InvalidDataException("PE signature");

        int optional = pe + 24;
        ushort magic = BitConverter.ToUInt16(bytes, optional);
        if (magic != 0x10b && magic != 0x20b)
            throw new InvalidDataException("Optional header");
        return BitConverter.ToUInt16(bytes, optional + 68);
    }
}
