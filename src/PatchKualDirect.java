import java.nio.file.*;
import java.util.zip.*;
import java.io.*;
import org.objectweb.asm.*;

/** Add an optional direct-home branch; preserve every original method. */
public class PatchKualDirect implements Opcodes {
  static final String OWNER="com/mobileread/ixtab/kindlelauncher/KualBooklet";
  static byte[] patch(byte[] input) {
    ClassReader r=new ClassReader(input);
    ClassWriter w=new ClassWriter(r,ClassWriter.COMPUTE_MAXS);
    int[] hits={0};
    r.accept(new ClassVisitor(ASM9,w) {
      public MethodVisitor visitMethod(int a,String n,String d,String s,String[] e) {
        if(n.equals("kt3DirectHome"))throw new IllegalStateException("Already patched");
        MethodVisitor m=super.visitMethod(a,n,d,s,e);
        if(!n.equals("longStart")||!d.equals("()V"))return m;
        hits[0]++;
        return new MethodVisitor(ASM9,m) {
          public void visitCode() {
            super.visitCode();
            visitMethodInsn(INVOKESTATIC,OWNER,"kt3DirectHome","()Z",false);
            Label original=new Label();visitJumpInsn(IFEQ,original);
            visitInsn(RETURN);visitLabel(original);
          }
        };
      }
      public void visitEnd() {
        MethodVisitor m=super.visitMethod(ACC_PRIVATE|ACC_STATIC,"kt3DirectHome","()Z",null,null);
        m.visitCode();Label start=new Label(),fallback=new Label(),end=new Label(),failure=new Label();
        m.visitTryCatchBlock(start,end,failure,"java/lang/Exception");m.visitLabel(start);
        m.visitTypeInsn(NEW,"java/io/File");m.visitInsn(DUP);
        m.visitLdcInsn("/mnt/us/kt3-home/USE_KUAL_MENU");
        m.visitMethodInsn(INVOKESPECIAL,"java/io/File","<init>","(Ljava/lang/String;)V",false);
        m.visitMethodInsn(INVOKEVIRTUAL,"java/io/File","exists","()Z",false);
        m.visitJumpInsn(IFNE,fallback);
        m.visitTypeInsn(NEW,"java/io/File");m.visitInsn(DUP);
        m.visitLdcInsn("/opt/kt3-home/app/open-direct.sh");
        m.visitMethodInsn(INVOKESPECIAL,"java/io/File","<init>","(Ljava/lang/String;)V",false);
        m.visitMethodInsn(INVOKEVIRTUAL,"java/io/File","isFile","()Z",false);
        m.visitJumpInsn(IFEQ,fallback);
        m.visitMethodInsn(INVOKESTATIC,"java/lang/Runtime","getRuntime","()Ljava/lang/Runtime;",false);
        m.visitLdcInsn("/bin/sh /opt/kt3-home/app/open-direct.sh");
        m.visitMethodInsn(INVOKEVIRTUAL,"java/lang/Runtime","exec","(Ljava/lang/String;)Ljava/lang/Process;",false);
        m.visitInsn(POP);m.visitLabel(end);m.visitInsn(ICONST_1);m.visitInsn(IRETURN);
        m.visitLabel(failure);m.visitInsn(POP);m.visitLabel(fallback);m.visitInsn(ICONST_0);m.visitInsn(IRETURN);
        m.visitMaxs(0,0);m.visitEnd();super.visitEnd();
      }
    },0);
    if(hits[0]!=1)throw new IllegalStateException("Unexpected entry point count");
    return w.toByteArray();
  }
  public static void main(String[] args)throws Exception {
    try(ZipFile z=new ZipFile(args[0]);ZipOutputStream out=new ZipOutputStream(Files.newOutputStream(Path.of(args[1])))) {
      var en=z.entries();int changed=0;
      while(en.hasMoreElements()) {
        ZipEntry e=en.nextElement();byte[] data=z.getInputStream(e).readAllBytes();
        if(e.getName().equals(OWNER+".class")){data=patch(data);changed++;}
        ZipEntry target=new ZipEntry(e.getName());target.setTime(e.getTime());out.putNextEntry(target);out.write(data);out.closeEntry();
      }
      if(changed!=1)throw new IllegalStateException("Missing class");
    }
    System.out.println("Patched only KualBooklet.longStart + optional fixed launch helper");
  }
}
