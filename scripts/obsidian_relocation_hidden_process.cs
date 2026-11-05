using System;
using System.Diagnostics;
using System.Threading.Tasks;

internal static class HiddenProcess
{
    internal static int Run(string executable, string arguments, string workingDirectory)
    {
        using (Process child = new Process())
        {
            child.StartInfo = new ProcessStartInfo
            {
                FileName = executable,
                Arguments = arguments,
                WorkingDirectory = workingDirectory,
                UseShellExecute = false,
                CreateNoWindow = true,
                WindowStyle = ProcessWindowStyle.Hidden,
                RedirectStandardOutput = true,
                RedirectStandardError = true
            };

            if (!child.Start())
                return 1;

            Task<string> stdout = Task.Factory.StartNew(
                () => child.StandardOutput.ReadToEnd());
            Task<string> stderr = Task.Factory.StartNew(
                () => child.StandardError.ReadToEnd());
            child.WaitForExit();
            Task.WaitAll(stdout, stderr);
            return child.ExitCode;
        }
    }
}
