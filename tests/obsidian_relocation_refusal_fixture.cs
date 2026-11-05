using System;
internal static class RelocationRefusalFixture
{
    private static int Main(string[] args)
    {
        // Exact no-argument interface; final pins deliberately absent.
        if (args.Length != 0) return 64;
        return 78; // NOT INSTALLABLE, no child invocation.
    }
}
