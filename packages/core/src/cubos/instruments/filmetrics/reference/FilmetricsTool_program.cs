using System;
using System.IO;
using System.Windows.Forms;

namespace FilmetricsTool
{
    public class FormFIRemote
    {
        private Filmetrics.FIRemote mFIRemote;
        private bool mHasMultipleMeasurementChannels;
        private Guid mSelectedMeasChannelOrSystemGuid;
        private bool mSingleSystemMeasureInProcess;

        public void InitializeFIRemote()
        {
            try
            {
                Filmetrics.FIRemote.ConstructorWarning theWarning = Filmetrics.FIRemote.ConstructorWarning.None;
                string warningMessage = "";

                mFIRemote = new Filmetrics.FIRemote(Filmetrics.FIRemote.GraphicalUserInterfaceType.None,
                                                   Filmetrics.FIRemote.GraphicalUserInterfaceStartupState.Hidden,
                                                   0,
                                                   ref theWarning, ref warningMessage);

                if (theWarning != Filmetrics.FIRemote.ConstructorWarning.None)
                {
                    Console.WriteLine("Startup warning. Message is: " + warningMessage);
                }

                if (mFIRemote.MeasChannelGuids.Count == 0)
                {
                    Console.WriteLine("No measurement systems found.");
                    return;
                }
            }
            catch (Exception ex)
            {
                Console.WriteLine("Error initializing FIRemote: " + ex.Message);
            }
        }
        public void AcquireSample()
        {
            try
            {
                if (mHasMultipleMeasurementChannels)
                {
                    mFIRemote.BaselineAcquireSpectrumFromSample(mSelectedMeasChannelOrSystemGuid);
                }
                else
                {
                    mFIRemote.BaselineAcquireSpectrumFromSample();
                }

                Console.WriteLine("Spectrum acquisition for sample completed successfully.");
            }
            catch (Filmetrics.FIRemote.AcquisitionException ex)
            {
                if (string.IsNullOrEmpty(ex.Message))
                {
                    Console.WriteLine("Spectrum acquisition error.");
                }
                else
                {
                    Console.WriteLine("Error attempting to acquire spectrum. Exception message is: " + Environment.NewLine + ex.Message);
                }
            }
            catch (Exception ex)
            {
                Console.WriteLine("Unknown Exception caught! " + ex.ToString());
            }
        }
        public void AcquireReference(string refSta)
        {
            try
            {
                Console.WriteLine("The reference standard is: " + refSta);
                mFIRemote.BaselineSetRefMat(refSta);

                bool skipSampleMeasurement = false;
                Console.WriteLine("Acquiring reference spectrum...");
                if (skipSampleMeasurement)
                {
                    bool useOldSampleSpec = true; 

                    if (useOldSampleSpec)
                    {
                        if (mHasMultipleMeasurementChannels)
                        {
                            mFIRemote.BaselineAcquireReferenceUsingOldSampleReflectance(mSelectedMeasChannelOrSystemGuid);
                        }
                        else
                        {
                            mFIRemote.BaselineAcquireReferenceUsingOldSampleReflectance();
                        }
                        Console.WriteLine("Reference spectrum acquired successfully.");
                    }
                    else
                    {
                        if (mHasMultipleMeasurementChannels)
                        {
                            mFIRemote.BaselineAcquireReference(mSelectedMeasChannelOrSystemGuid);
                        }
                        else
                        {
                            mFIRemote.BaselineAcquireReference();
                        }
                        Console.WriteLine("Reference spectrum acquired successfully.");
                    }
                }
                else
                {
                    if (mHasMultipleMeasurementChannels)
                    {
                        mFIRemote.BaselineAcquireReference(mSelectedMeasChannelOrSystemGuid);
                    }
                    else
                    {
                        mFIRemote.BaselineAcquireReference();
                    }
                    Console.WriteLine("Reference spectrum acquired successfully.");
                }
            }
            catch (Filmetrics.FIRemote.AcquisitionException ex)
            {
                Console.WriteLine("Error attempting to acquire spectrum. Exception message is: " + ex.Message);
            }
            catch (Exception ex)
            {
                Console.WriteLine("Unknown Exception caught! " + ex.ToString());
            }
        }
        public void AcquireBackground()
        {
            try
            {
                Console.WriteLine("Acquiring background spectrum...");

                if (mHasMultipleMeasurementChannels)
                {
                    mFIRemote.BaselineAcquireBackgroundAfterRef(mSelectedMeasChannelOrSystemGuid);
                }
                else
                {
                    mFIRemote.BaselineAcquireBackgroundAfterRef();
                }

                Console.WriteLine("Background spectrum acquired successfully.");
            }
            catch (Filmetrics.FIRemote.AcquisitionException ex)
            {
                if (string.IsNullOrEmpty(ex.Message))
                {
                    Console.WriteLine("Spectrum acquisition error.");
                }
                else
                {
                    Console.WriteLine("Error during spectrum acquisition: " + ex.Message);
                }
            }
            catch (Filmetrics.FIRemote.InvalidBackgroundException)
            {
                Console.WriteLine("Background and reference spectra are nearly identical. Please ensure the reference sample is removed and try again.");
                Console.WriteLine("If the issue persists, restart the baseline procedure from the beginning.");
            }
            catch (Exception ex)
            {
                Console.WriteLine("Unexpected exception: " + ex.ToString());
            }
        }
        public void Measure()
        {
            try
            {
                Console.WriteLine("Starting measurement...");
                Filmetrics.FIRemote.FIMeasResults theResults = null;

                try
                {
                    mSingleSystemMeasureInProcess = true;
                    theResults = mFIRemote.Measure(false);
                }
                finally
                {
                    mSingleSystemMeasureInProcess = false;
                }

                Console.WriteLine("Measurement Results (System):");
                Console.WriteLine(theResults.ResultsSummary);
                Console.WriteLine("Measurement Complete");
            }

            catch (Filmetrics.FIRemote.AcquisitionException acEx)
            {
                switch (acEx.Type)
                {
                    case Filmetrics.FIRemote.AcquisitionException.ExceptionType.Saturation:
                        Console.WriteLine("Error: Spectrometer saturation. Repeat baseline or reduce integration time.");
                        break;
                    case Filmetrics.FIRemote.AcquisitionException.ExceptionType.InvalidAcquisitionSettings:
                        Console.WriteLine("Error: Invalid acquisition settings. Verify that a valid baseline has been established.");
                        break;
                    default:
                        Console.WriteLine("Acquisition error: " + (string.IsNullOrEmpty(acEx.Message) ? "Unknown acquisition error." : acEx.Message));
                        break;
                }
            }
            catch (Filmetrics.FIRemote.SpectrumAnalysisException analysisEx)
            {
                Console.WriteLine("Spectrum analysis error: " + analysisEx.Message);
            }
            catch (Exception ex)
            {
                Console.WriteLine("General exception caught: " + ex.ToString());
            }
        }
        public void CommitBaseline()
        {
            try
            {
                if (mHasMultipleMeasurementChannels)
                {
                    mFIRemote.BaselineCommit(mSelectedMeasChannelOrSystemGuid);
                }
                else
                {
                    mFIRemote.BaselineCommit();
                }

                Console.WriteLine("Baseline committed successfully.");
            }
            catch (Filmetrics.FIRemote.TimeOutException ex)
            {
                Console.WriteLine("Timeout occurred while committing baseline. Message: " + ex.Message);
            }
            catch (Exception ex)
            {
                Console.WriteLine("Exception caught while committing baseline: " + ex.ToString());
            }
        }
        public void AuthenticateReferenceBackground()
        {
            try
            {
                if (mHasMultipleMeasurementChannels)
                {
                    mFIRemote.AuthenticateRefBac(mSelectedMeasChannelOrSystemGuid);
                }
                else
                {
                    mFIRemote.AuthenticateRefBac();
                }
            }
            catch (Filmetrics.FIRemote.IllegalCommandException acEx)
            {
                Console.WriteLine("Error: " + acEx.Message);
            }
            catch (Exception ex)
            {
                Console.WriteLine("Exception caught! " + ex.ToString());
            }
        }
        public void CheckBaselineHardwareAdjustStatus()
        {
            try
            {
                Filmetrics.FIRemote.BaselineHardwareAdjustStatus theStatus = null;

                if (mHasMultipleMeasurementChannels)
                {
                    theStatus = mFIRemote.GetBaselineHardwareAdjustStatus(mSelectedMeasChannelOrSystemGuid);
                }
                else
                {
                    theStatus = mFIRemote.GetBaselineHardwareAdjustStatus();
                }

                Console.WriteLine("Baseline Hardware Adjustment Status:");
                Console.WriteLine("Needs Periodic Adjustment: " + theStatus.NeedsPeriodicAdjustment);
                Console.WriteLine("Adjustment Required Now: " + theStatus.AdjustmentRequiredNow);
                Console.WriteLine("Adjustment Recommended Now: " + theStatus.AdjustmentRecommendedNow);
                Console.WriteLine("Time to Next Recommended Adjustment (hrs): " + theStatus.TimeToNextRecommendedAdjustmentHours);
                Console.WriteLine("Adjustment Period (hrs): " + theStatus.AdjustmentPeriodHours);
            }
            catch (Exception ex)
            {
                Console.WriteLine("Exception caught: " + ex.ToString());
            }
        }
        public void SetRecipe(string RecipeName)
        {
            string recipeName = RecipeName;
            try
            {
                if (mHasMultipleMeasurementChannels)
                {
                    mFIRemote.SetRecipe(mSelectedMeasChannelOrSystemGuid, recipeName);
                }
                else
                {
                    mFIRemote.SetRecipe(recipeName);
                }
                Console.WriteLine("Recipe set");
            }
            catch (Filmetrics.FIRemote.IllegalCommandException icEx)
            {
                Console.WriteLine(icEx.Message, "Error");
            }
            catch (Filmetrics.FIRemote.FileNotFoundException)
            {
                Console.WriteLine("Recipe " + recipeName + " is missing. Unable to set recipe.", "Error");
            }
            catch (Exception ex)
            {
                Console.WriteLine("Exception caught in ButtonSetRecipe_Click " + ex.ToString());
            }
        }
        public void SetRecipeMode()
        {
            try
            {
                mFIRemote.SetRecipeModeToThickness();
                Console.WriteLine("Recipe mode set");
            }
            catch (Filmetrics.FIRemote.IllegalCommandException icEx)
            {
                Console.WriteLine("Error: " + icEx.Message);
            }
            catch (Exception ex)
            {
                Console.WriteLine("Exception caught in SetRecipeModeFromCommandLine: " + ex.ToString());
            }
        }
        public void SaveSpectrumToFixedPath()
        {
            try
            {
                string filePath = @"C:\Users\KABLab\Desktop\Filmetrics Framework\example.csv";
                mFIRemote.SaveSpectrum(filePath);
                Console.WriteLine($"Spectrum successfully saved to: {filePath}");
            }
            catch (Exception ex)
            {
                Console.WriteLine("Exception caught! " + ex.ToString());
            }
        }
        public void SaveSpectrumToPath(string wellId)
        {
            try
            {
                string filePath = $@"C:\Users\KABLab\Desktop\Filmetrics Framework\Spectrum_{wellId}.csv";
                mFIRemote.SaveSpectrum(filePath);
                Console.WriteLine($"Spectrum saved to: {filePath} successfully");
            }
            catch (Exception ex)
            {
                Console.WriteLine("Exception caught! " + ex.ToString());
            }
        }

        public void SystemClose ()
        {
            try
            {
                mFIRemote.Dispose();
            }
            catch (Exception ex)
            {
                Console.WriteLine("Exception caught! " + ex.ToString());
            }
        }
    }

    internal static class Program
    {
        static void Main(string[] args)
        {
            Console.Write("Initializing FIRemote");
            FormFIRemote controller = new FormFIRemote();
            controller.InitializeFIRemote();
            controller.SetRecipeMode();
            controller.SetRecipe(args[0]);
            Console.Write("Initializition Complete");

            while (true)
            {
                string input = Console.ReadLine();
                if (string.IsNullOrEmpty(input)) continue;
                string[] Args = input.Split(' ');
                string cmd = Args[0].ToLower();

                switch (cmd)
                {
                    case "sample":
                        controller.AcquireSample();
                        break;
                    case "reference":
                        string RefSta = Args.Length > 1 ? Args[1] : null;
                        controller.AcquireReference(RefSta);
                        break;
                    case "background":
                        controller.AcquireBackground();
                        break;
                    case "commit":
                        controller.CommitBaseline();
                        break;
                    case "measure":
                        controller.Measure();
                        break;
                    case "save":
                        string path = Args.Length > 1 ? Args[1] : null;
                        controller.SaveSpectrumToPath(path);
                        break;
                    case "exit":
                        Console.WriteLine("Exiting...");  
                        controller.SystemClose();
                        return;
                    default:
                        Console.WriteLine("Unknown command.");
                        break;
                }
            }
        }

    }
}


