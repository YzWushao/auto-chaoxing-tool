import com.android.manifmerger.ManifestMerger2;
import com.android.manifmerger.MergingReport;
import com.android.manifmerger.ManifestSystemProperty;
import com.android.utils.StdLogger;
import java.io.File;
import java.nio.file.Files;
import java.nio.file.Path;

public class MergeManifest {
    public static void main(String[] args) throws Exception {
        var merger=ManifestMerger2.newMerger(new File(args[0]),new StdLogger(StdLogger.Level.WARNING),ManifestMerger2.MergeType.APPLICATION)
            .setNamespace("top.autochaoxing.mobile")
            .setPlaceHolderValue("applicationId","top.autochaoxing.mobile")
            .setOverride(ManifestSystemProperty.UsesSdk.MIN_SDK_VERSION,"26")
            .setOverride(ManifestSystemProperty.UsesSdk.TARGET_SDK_VERSION,"35")
            .setOverride(ManifestSystemProperty.Manifest.VERSION_CODE,args[2])
            .setOverride(ManifestSystemProperty.Manifest.VERSION_NAME,args[3]);
        for(int i=4;i<args.length;i++)merger.addLibraryManifest(new File(args[i]));
        var report=merger.merge();
        if(report.getResult()==MergingReport.Result.ERROR)throw new IllegalStateException(report.getReportString());
        Files.writeString(Path.of(args[1]),report.getMergedDocument(MergingReport.MergedManifestKind.MERGED));
    }
}
