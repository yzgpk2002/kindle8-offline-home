import java.util.zip.*;
import org.objectweb.asm.*;
import org.objectweb.asm.tree.*;
import org.objectweb.asm.tree.analysis.*;
public class VerifyKualDirect {
 public static void main(String[] args)throws Exception {
  try(ZipFile z=new ZipFile(args[0])) {
   ClassNode c=new ClassNode();new ClassReader(z.getInputStream(z.getEntry("com/mobileread/ixtab/kindlelauncher/KualBooklet.class"))).accept(c,0);
   if(c.version!=48)throw new AssertionError("Runtime class version changed");
   for(MethodNode m:c.methods)new Analyzer<BasicValue>(new BasicVerifier()).analyze(c.name,m);
   System.out.println("PASS bytecode stack/type analysis: "+c.methods.size()+" methods; class version 48 retained");
  }
 }
}
